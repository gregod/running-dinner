#!/usr/bin/env python3
"""
CLI that solves a real-world running dinner optimization problem.
See https://www.godberit.de/blog/2024-04-24-operations-research-for-social-dinners/ for details

Single file, only various travel-time backends contained in travel_times/*. 
MOTIS is recommended for support of public transit.
"""

from pulp import *

import itertools
import math
from tqdm import tqdm
from datetime import datetime
import argparse
import os
import csv
import sys
import json

from travel_times import InterfaceTravelTimeEngine
from travel_times.motis import MotisTravelTimeEngine

if __name__ != "__main__":
    raise Exception("Is CLI, must not be imported")

# map initial output to stderr
orig_out = sys.stdout
sys.stdout = sys.stderr


# argparser setup
def valid_datetime_type(arg_datetime_str):
    """custom argparse type for user datetime values given from the command line"""
    try:
        date = datetime.strptime(arg_datetime_str, "%Y-%m-%d %H:%M")
        if date <= datetime.now():
            raise argparse.ArgumentTypeError("Given date must be in the future")
        return date
    except ValueError:
        msg = "Given Datetime ({0}) not valid! Expected format, 'YYYY-MM-DD HH:mm'!".format(
            arg_datetime_str
        )
        raise argparse.ArgumentTypeError(msg)


def is_valid_file(arg):
    if not os.path.exists(arg) or os.path.isdir(arg):
        raise argparse.ArgumentTypeError("The file %s does not exist!" % arg)
    else:
        return arg


parser = argparse.ArgumentParser(
    description="""
Tool to create dinner plan.
Cost Function is: max(teamDuration) - 0.3 * avg(teamDuration) - sum(matchedPreferences)
"""
)

parser.add_argument(
    "--datetime-1",
    type=valid_datetime_type,
    default=None,
    required=True,
    help='Start time of 1st course in format "YYYY-MM-DD HH:mm"',
)

parser.add_argument(
    "--datetime-2",
    type=valid_datetime_type,
    default=None,
    required=False,
    help='Start time of 2nd course in format "YYYY-MM-DD HH:mm" defaults to first course start time',
)

parser.add_argument(
    "--datetime-3",
    type=valid_datetime_type,
    default=None,
    required=False,
    help='Start time of 3rd course in format "YYYY-MM-DD HH:mm" defaults to first course start time',
)

parser.add_argument(
    "--datetime-afterparty",
    type=valid_datetime_type,
    default=None,
    required=False,
    help='Start time of the afterparty in format "YYYY-MM-DD HH:mm" defaults to first course start time',
)

parser.add_argument(
    "--timeout",
    type=int,
    default=3600,
    help="Number of seconds to spend on optimisation.",
)

parser.add_argument(
    "--large-teams",
    type=int,
    default=0,
    help="Number of large teams to determine. Large teams will not meet",
)


parser.add_argument("--min-travel", type=int, default=1, help="Minimum Travel Time")

parser.add_argument(
    "--cook-incompatible",
    type=lambda s: [int(item) for item in s.split(",")],
    default=[],
    help="Teams that must not cook for each other. (Meeting otherwise is fine)",
)

parser.add_argument("--num-courses", type=int, default=3, help="Number of courses")

parser.add_argument(
    "--can-meet-again",
    action="store_true",
    default=False,
    help="Allow teams to meet more than once during all courses",
)


parser.add_argument(
    "--can-stay",
    action="store_true",
    default=False,
    help="Can stay at locations with travel time <=1",
)

parser.add_argument(
    "--ignore-preferences",
    action="store_true",
    default=False,
    help="Ignore the preferences",
)

parser.add_argument(
    "--asymetric-distances",
    action="store_true",
    default=False,
    help="Assume asymetric distances",
)

parser.add_argument(
    "--ignore-avg-dist",
    action="store_true",
    default=False,
    help="Remove average distance from cost function",
)
parser.add_argument(
    "--ignore-max-dist",
    action="store_true",
    default=False,
    help="Remove max distance from cost function",
)

parser.add_argument("--afterparty", help="Address of the Afterparty")


parser.add_argument(
    "file",
    help="input CSV file with team information. Include header (team_name,address,scoreCourse1,scoreCourse2,scoreCourse3) ",
    metavar="<CSV FILE>",
    type=is_valid_file,
)

args = parser.parse_args()

# set datetime defaults
if args.datetime_2 is None:
    args.datetime_2 = args.datetime_1
if args.datetime_3 is None:
    args.datetime_3 = args.datetime_1
if args.datetime_afterparty is None:
    args.datetime_afterparty = args.datetime_1

courses = list(range(0, args.num_courses))


datetimes = {0: args.datetime_1, 1: args.datetime_2, 2: args.datetime_3}


travel_time_engine: InterfaceTravelTimeEngine = MotisTravelTimeEngine()


data = []
with open(args.file, newline="") as csvfile:
    csvr = csv.reader(csvfile)
    headers = next(csvr, None)

    if len(headers) != (4 + args.num_courses) and not args.ignore_preferences:
        print("Malformed csv, less than 4 headers found:", len(headers))
        print("Please use format : 'name,addr,tel,diet,pref1,pref2,pref3'")
        print("Pass ignore_preferences to ignore")
        exit(1)

    if (
        len(headers) != 4
        and len(headers) != (4 + args.num_courses)
        and args.ignore_preferences
    ):
        print("Malformed csv, less than 4 headers found:", len(headers))
        print("Please use format : 'name,addr,tel,diet'")
        exit(1)

    for row in csvr:
        if args.ignore_preferences:
            data.append({"name": row[0], "addr": row[1], "tel": row[2], "diet": row[3]})
        else:
            d = {
                "name": row[0],
                "addr": row[1],
                "tel": row[2],
                "diet": row[3],
            }
            for c in courses:
                d[f"pref{c + 1}"] = float(row[4 + c])

            data.append(d)


if len(data) % len(courses) != 0:
    print(
        f"Error: The number of teams {len(data)} must be devisable by the number of courses {len(courses)}!"
    )
    exit(1)


distance_matrix = {}

# set indexes for easy access
for idx in range(len(data)):
    data[idx]["idx"] = idx

# team_name, adresse, perf1, pref2, pref3

print(f"Geocoding of adresses using {travel_time_engine.name()} API:")
for i in tqdm(data, unit="address"):
    data[i["idx"]]["geo"] = travel_time_engine.get_geo(i["addr"])

if args.afterparty is not None:
    afterparty_geo = travel_time_engine.get_geo(args.afterparty)
print()


print(f"Getting distances using {travel_time_engine.name()} API:")
# made assumption that distance matrix is symetric

pair_function = (
    itertools.permutations if args.asymetric_distances else itertools.combinations
)
pairs = list(pair_function(data, 2))

count_distance_matrix = len(pairs)
for a, b in tqdm(pairs, unit="route"):
    for c in courses:
        try:
            route_time = travel_time_engine.route_between_points(
                a["geo"], b["geo"], time=datetimes[c]
            )
            distance_matrix[(a["idx"], b["idx"], c)] = route_time

            if not args.asymetric_distances:
                distance_matrix[(b["idx"], a["idx"], c)] = route_time

        except Exception as ex:
            print(a["geo"].name, " to ", b["geo"].name, "; direct at ", direct_distance)
            raise ex


print()

print("Getting distances to Afterparty")
for t in tqdm(range(len(data))):
    for c in courses:
        distance_matrix[(t, t, c)] = 0

    if args.afterparty is not None:
        dist = travel_time_engine.route_between_points(
            data[t]["geo"], afterparty_geo, time=args.datetime_afterparty
        )
    else:
        dist = 0
    distance_matrix[(t, "afterparty")] = dist

print()

# find teams at same adress:

same_addr_team = {}
for t in data:
    if t["addr"] not in same_addr_team:
        same_addr_team[t["addr"]] = [t]
    else:
        same_addr_team[t["addr"]].append(t)


# everything is ready for the optimisation!
print("Creating Optimization Model")
groups = range(int(len(data) / len(courses)))
teams = range(len(data))

prob = LpProblem("AssignmentProblem", LpMinimize)

assignment = LpVariable.dicts(
    "assignment",
    ((t, g, c) for t in teams for g in groups for c in courses),
    0,
    1,
    LpBinary,
)
chef = LpVariable.dicts(
    "chef", ((t, g, c) for t in teams for g in groups for c in courses), 0, 1, LpBinary
)

# route between i and j for team t in group g and course c
arc = LpVariable.dicts(
    "arc",
    (
        (c, i, j, t, g)
        for c in courses
        for i in teams
        for j in teams
        for t in teams
        for g in groups
    ),
    0,
    1,
    LpBinary,
)


maxDuration = LpVariable("maxDuration", lowBound=0)


max_pref = (
    0
    if args.ignore_preferences
    else max([data[t][f"pref{c + 1}"] for t in teams for c in courses])
)


preferences = (
    0
    if args.ignore_preferences
    else (
        lpSum(
            [
                chef[(t, g, c)] * data[t][f"pref{c + 1}"] / max_pref
                for t in teams
                for g in groups
                for c in courses
                if data[t][f"pref{c + 1}"] > -1000
            ]
        )
    )
)


distance_sum = (
    0
    if args.ignore_avg_dist
    else lpSum(
        [
            arc[(c, i, j, t, g)]
            * (
                (distance_matrix[(j, "afterparty")] if c == courses[-1] else 0)
                + distance_matrix[(i, j, c)]
            )
            for t in teams
            for c in courses
            for i in teams
            for j in teams
            for g in groups
            if j is not i
        ]
    )
)

prob += (
    (0 if args.ignore_max_dist else maxDuration)
    + 0.1 * (1 / len(teams) * distance_sum)
    - (20 * preferences)
)


# Assign every team to one group per course
for t in teams:
    for c in courses:
        prob += lpSum([assignment[(t, g, c)] for g in groups]) == 1

# evey group and team has one member for every course
for g in groups:
    for c in courses:
        prob += lpSum([assignment[(t, g, c)] for t in teams]) == len(courses)


# teams can only meet once
if not args.can_meet_again:
    print("Ensuring that teams meet only once ...")
    for c1 in range(len(courses)):
        for c2 in range(c1 + 1, len(courses)):
            for g1 in groups:
                for g2 in groups:
                    for t1 in range(len(teams)):
                        for t2 in range(t1 + 1, len(teams)):
                            prob += (
                                assignment[(teams[t1], g1, courses[c1])]
                                + assignment[(teams[t2], g1, courses[c1])]
                                + assignment[(teams[t1], g2, courses[c2])]
                                + assignment[(teams[t2], g2, courses[c2])]
                                <= 3
                            )


# temp fix no chef
if not args.ignore_preferences:
    for t in teams:
        for c in courses:
            if data[t][f"pref{c + 1}"] <= -1000:
                print(f"Forbidding {c + 1}. course for", data[t]["name"])
                for g in groups:
                    prob += chef[(t, g, c)] == 0


# every group must have one chef per course
for g in groups:
    for c in courses:
        prob += lpSum([chef[(t, g, c)] for t in teams]) == 1


# every team is chef at most one
for t in teams:
    prob += lpSum([chef[(t, g, c)] for g in groups for c in courses]) == 1


# only be chef if assigned
for t in teams:
    for g in groups:
        for c in courses:
            prob += chef[(t, g, c)] <= assignment[(t, g, c)]


# only have arc when assigned
for t in teams:
    for g in groups:
        for c in courses:
            prob += (
                lpSum([arc[(c, i, j, t, g)] for i in teams for j in teams])
                == assignment[t, g, c]
            )

# cant have more than one team moving between source and target for a course
# for c in courses:
#    for source in teams:
#        for target in teams:
#            prob += lpSum([  arc[ (c, source,target, t, g)] for t in teams for g in groups ]) <= 1


# start at self if assigned
for t in teams:
    for g in groups:
        prob += (
            lpSum([arc[(courses[0], t, j, t, g)] for j in teams])
            == assignment[(t, g, courses[0])]
        )

# go only to chef
for c in courses:
    for t in teams:
        for g in groups:
            for i in teams:
                for j in teams:
                    prob += arc[(c, i, j, t, g)] <= chef[(j, g, c)]

# can only leave if entering
for c in range(1, len(courses)):
    for t in teams:
        for i in teams:
            prob += lpSum(
                [
                    arc[(courses[c], i, j, t, g)]
                    for j in teams
                    for g in groups
                    if j is not i
                ]
            ) == lpSum(
                [arc[(courses[c - 1], r, i, t, g)] for r in teams for g in groups]
            )


# max dist constraint
if not args.ignore_max_dist:
    for t in teams:
        prob += (
            lpSum(
                [
                    arc[(c, i, j, t, g)]
                    * (
                        (distance_matrix[(j, "afterparty")] if c == courses[-1] else 0)
                        + distance_matrix[(i, j, c)]
                    )
                    for c in courses
                    for i in teams
                    for j in teams
                    for g in groups
                    if j is not i
                ]
            )
            <= maxDuration
        )


# have minimum time constraint
for t in teams:
    prob += (
        lpSum(
            [
                arc[(c, i, j, t, g)] * (distance_matrix[(i, j, c)])
                for c in courses
                for i in teams
                for j in teams
                for g in groups
                if j is not i
            ]
        )
        >= args.min_travel
    )


# forbid any arc with a travel time of <= 1
if not args.can_stay:
    for t in teams:
        for c in courses:
            for g in groups:
                for j in teams:
                    for i in teams:
                        if i is not j:
                            if distance_matrix[(i, j, c)] <= 1:
                                prob += arc[(c, i, j, t, g)] == 0


for t1, t2 in itertools.combinations(args.cook_incompatible, 2):
    for c in courses:
        for g in groups:
            prob += assignment[(t1, g, c)] <= 1 - chef[(t2, g, c)]

if args.large_teams > 0:
    large_team = LpVariable.dicts("largeTeam", teams, 0, 1, LpInteger)

    prob += lpSum([large_team[t] for t in teams]) == args.large_teams
    # two large teams must not meet
    for c in courses:
        for g in groups:
            for t1 in teams:
                for t2 in teams:
                    if t1 != t2:
                        prob += (
                            assignment[(t1, g, c)]
                            + assignment[(t2, g, c)]
                            + large_team[t1]
                            + large_team[t2]
                            <= 3
                        )


# teams with same address must not cook within the same course
for addr, dup_teams in same_addr_team.items():
    if len(dup_teams) > 1:
        print("Forbidding same course of", len(dup_teams), "teams at", addr)
        for c in courses:
            prob += lpSum(
                [chef[(i["idx"], g, c)] for i in dup_teams for g in groups]
            ) <= max(1, math.ceil(len(dup_teams) / len(courses)))


solver = None
if GUROBI_CMD().available():
    solver = GUROBI_CMD(options=[("TimeLimit", args.timeout)], msg=1)
    # solver = GUROBI(timeLimit=args.timeout,msg=1)
    print("Loaded solver gurobi")
elif CPLEX().available():
    print("Loaded solver CPLEX")
    solver = CPLEX(timeLimit=args.timeout, msg=1)
else:
    print(
        "Warning: Loaded fallback solver. Install Gurobi or CPLEX for better performance."
    )
    solver = PULP_CBC_CMD(timeLimit=args.timeout, msg=1)


print(
    "Solving... Please wait for the end of your time limit of", args.timeout, "seconds"
)
prob.solve(solver)

print("Status:", LpStatus[prob.status])
print("Total Costs = ", value(prob.objective))

print()
print("Solution:")
print()
if args.large_teams > 0:
    print("Large Team Info:")
    print("----------------")
    for t in teams:
        if value(large_team[t]) == 1:
            print(data[t]["name"], "is a large team")
    print()


print()
print("Group View:")
print("-----------")

coursedata = []
"""
courses : [
    [ { guest : [1,2], cook : 2 },{ guest : [1,2], cook : 2 }]
]

"""
for c in courses:
    print("Course %s" % c)
    mycourse = []
    for g in groups:
        print("\tGroup %d" % g)
        mygroup = {"cook": None, "guests": []}
        for t in teams:
            if value(assignment[(t, g, c)]) == 1:
                if value(chef[(t, g, c)]) == 1:
                    mygroup["cook"] = t
                    print("\t\tChef %s" % data[t]["name"])
                else:
                    mygroup["guests"].append(t)
                    print("\t\tEat %s" % data[t]["name"])
        mycourse.append(mygroup)
    coursedata.append(mycourse)
print()
print("Team View:")
print("----------")
team_distances = []
teamdata = []

for t in teams:
    obj = {
        "idx": t,
        "name": data[t]["name"],
        "tel": data[t]["tel"],
        "diet": data[t]["diet"],
        "address": data[t]["addr"],
        "tour": [],
    }
    teamdata.append(obj)

for t in teams:
    print("Team %s" % (data[t]["name"]))
    sumdistance = 0
    for c in courses:
        for i in teams:
            for j in teams:
                for g in groups:
                    if value(arc[(c, i, j, t, g)]) == 1:
                        if value(chef[(t, g, c)]) == 1:
                            print(
                                "\tFor %s from %s to %s taking %d minutes and cook"
                                % (
                                    c,
                                    data[i]["name"],
                                    data[j]["name"],
                                    distance_matrix[(i, j, c)],
                                )
                            )
                            if not args.ignore_preferences:
                                if c == 0:
                                    if data[t]["pref1"] < 0:
                                        print("\t\tAgainst preference")
                                    elif data[t]["pref1"] > 0:
                                        print("\t\tFollowing preference")
                                if c == 1:
                                    if data[t]["pref2"] < 0:
                                        print("\t\tAgainst preference")
                                    elif data[t]["pref2"] > 0:
                                        print("\t\tFollowing preference")
                                if c == 2:
                                    if data[t]["pref3"] < 0:
                                        print("\t\tAgainst preference")
                                    elif data[t]["pref3"] > 0:
                                        print("\t\tFollowing preference")

                        else:
                            print(
                                "\tFor %s from %s to %s taking %d minutes"
                                % (
                                    c,
                                    data[i]["name"],
                                    data[j]["name"],
                                    distance_matrix[(i, j, c)],
                                )
                            )

                        teamdata[t]["tour"].append(
                            {
                                "approx_duration": distance_matrix[(i, j, c)],
                                "group": g,
                                "gang": c,
                            }
                        )

                        sumdistance += distance_matrix[(i, j, c)]

                        if c == courses[-1]:
                            print(
                                "\tFor Afterparty from %s taking %d minutes"
                                % (data[j]["name"], distance_matrix[(j, "afterparty")])
                            )
                            du = distance_matrix[(j, "afterparty")]
                            teamdata[t]["afterparty_duration"] = du
                            sumdistance += du
    team_distances.append(sumdistance)

print()
print("Statistics:")
print("-----------")

print(
    "Average travel time between courses:",
    int(sum(team_distances) / len(team_distances) / (len(courses) + 1)),
    "minutes",
)  # +1 for afterparty
print(
    "Average travel time for whole event:",
    int(sum(team_distances) / len(team_distances)),
    "minutes",
)
print(
    "Minimum/Maximum team whole event travel time:",
    min(team_distances),
    "/",
    max(team_distances),
    "minutes",
)
print()

sys.stdout = orig_out
print(json.dumps({"teams": teamdata, "courses": coursedata}))
