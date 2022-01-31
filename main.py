import json
import sys
from datetime import datetime
from functools import cmp_to_key
from requests.auth import HTTPBasicAuth
from requests import get
import argparse
import pytz

parser = argparse.ArgumentParser(description='Calculate the DORA metrics.')
parser.add_argument('--octopusUrl',
                    dest='octopus_url',
                    action='store',
                    help='The Octopus server URL',
                    required=True)
parser.add_argument('--octopusApiKey',
                    dest='octopus_api_key',
                    action='store',
                    help='The Octopus API key',
                    required=True)
parser.add_argument('--githubUser',
                    dest='github_user',
                    action='store',
                    help='The GitHub username',
                    required=True)
parser.add_argument('--githubToken',
                    dest='github_token',
                    action='store',
                    help='The GitHub token/password',
                    required=True)
parser.add_argument('--octopusSpace',
                    dest='octopus_space',
                    action='store',
                    help='The Octopus space',
                    required=True)
parser.add_argument('--octopusProject',
                    dest='octopus_project',
                    action='store',
                    help='A comma separated list of Octopus projects',
                    required=True)
parser.add_argument('--octopusEnvironment',
                    dest='octopus_environment',
                    action='store',
                    help='The Octopus environment',
                    required=True)
parser.add_argument("--output",
                    help="The output format",
                    dest='output',
                    nargs='?',
                    type=str,
                    const='text',
                    default='text',
                    choices=['text', 'json'],
                    required=False)

args = parser.parse_args()

headers = {"X-Octopus-ApiKey": args.octopus_api_key}
github_auth = HTTPBasicAuth(args.github_user, args.github_token)


def parse_github_date(date_string):
    if date_string is None:
        return None
    return datetime.strptime(date_string.replace("Z", "+0000"), '%Y-%m-%dT%H:%M:%S%z')


def parse_octopus_date(date_string):
    if date_string is None:
        return None
    return datetime.strptime(date_string[:-3] + date_string[-2:], '%Y-%m-%dT%H:%M:%S.%f%z')


def compare_dates(date1, date2):
    date1_parsed = parse_octopus_date(date1["Created"])
    date2_parsed = parse_octopus_date(date2["Created"])
    if date1_parsed < date2_parsed:
        return -1
    if date1_parsed == date2_parsed:
        return 0
    return 1


def get_space_id(space_name):
    url = args.octopus_url + "/api/spaces?partialName=" + space_name.strip() + "&take=1000"
    response = get(url, headers=headers)
    spaces_json = response.json()

    filtered_items = [a for a in spaces_json["Items"] if a["Name"] == space_name.strip()]

    if len(filtered_items) == 0:
        sys.stderr.write("The space called " + space_name + " could not be found.\n")
        return None

    first_id = filtered_items[0]["Id"]
    return first_id


def get_resource_id(space_id, resource_type, resource_name):
    if space_id is None:
        return None

    url = args.octopus_url + "/api/" + space_id + "/" + resource_type + "?partialName=" \
          + resource_name.strip() + "&take=1000"
    response = get(url, headers=headers)
    json = response.json()

    filtered_items = [a for a in json["Items"] if a["Name"] == resource_name.strip()]
    if len(filtered_items) == 0:
        sys.stderr.write("The resource called " + resource_name + " could not be found in space " + space_id + ".\n")
        return None

    first_id = filtered_items[0]["Id"]
    return first_id


def get_resource(space_id, resource_type, resource_id):
    if space_id is None:
        return None

    url = args.octopus_url + "/api/" + space_id + "/" + resource_type + "/" + resource_id
    response = get(url, headers=headers)
    json = response.json()

    return json


def get_deployments(space_id, environment_id, project_id):
    if space_id is None or environment_id is None or project_id is None:
        return None

    url = args.octopus_url + "/api/" + space_id + "/deployments?environments=" + environment_id + "&take=1000"
    response = get(url, headers=headers)
    json = response.json()

    filtered_items = [a for a in json["Items"] if a["ProjectId"] == project_id]
    if len(filtered_items) == 0:
        sys.stderr.write("The project id " + project_id + " did not have a deployment in " + space_id + ".\n")
        return None

    sorted_list = sorted(filtered_items, key=cmp_to_key(compare_dates), reverse=True)

    return sorted_list


def get_change_lead_time():
    change_lead_times = []
    space_id = get_space_id(args.octopus_space)
    environment_id = get_resource_id(space_id, "environments", args.octopus_environment)
    for project in args.octopus_project.split(","):
        project_id = get_resource_id(space_id, "projects", project)
        deployments = get_deployments(space_id, environment_id, project_id)
        for deployment in deployments:
            earliest_commit = None
            release = get_resource(space_id, "releases", deployment["ReleaseId"])
            for buildInfo in release["BuildInformation"]:
                for commit in buildInfo["Commits"]:
                    api_url = commit["LinkUrl"].replace("github.com", "api.github.com/repos") \
                        .replace("commit", "commits")
                    commit_response = get(api_url, auth=github_auth)
                    date_parsed = parse_github_date(commit_response.json()["commit"]["committer"]["date"])
                    if earliest_commit is None or earliest_commit > date_parsed:
                        earliest_commit = date_parsed
            if earliest_commit is not None:
                change_lead_times.append((parse_octopus_date(deployment["Created"]) - earliest_commit).total_seconds())
    if len(change_lead_times) != 0:
        return sum(change_lead_times) / len(change_lead_times)
    return None


def get_time_to_restore_service():
    restore_service_times = []
    space_id = get_space_id(args.octopus_space)
    environment_id = get_resource_id(space_id, "environments", args.octopus_environment)
    for project in args.octopus_project.split(","):
        project_id = get_resource_id(space_id, "projects", project)
        deployments = get_deployments(space_id, environment_id, project_id)
        for deployment in deployments:
            deployment_date = parse_octopus_date(deployment["Created"])
            release = get_resource(space_id, "releases", deployment["ReleaseId"])
            for buildInfo in release["BuildInformation"]:
                for work_item in buildInfo["WorkItems"]:
                    api_url = work_item["LinkUrl"].replace("github.com", "api.github.com/repos")
                    commit_response = get(api_url, auth=github_auth)
                    created_date = parse_github_date(commit_response.json()["created_at"])
                    if created_date is not None:
                        restore_service_times.append((deployment_date - created_date).total_seconds())
    if len(restore_service_times) != 0:
        return sum(restore_service_times) / len(restore_service_times)
    return None


def get_deployment_frequency():
    deployment_count = 0
    earliest_deployment = None
    latest_deployment = None
    space_id = get_space_id(args.octopus_space)
    environment_id = get_resource_id(space_id, "environments", args.octopus_environment)
    for project in args.octopus_project.split(","):
        project_id = get_resource_id(space_id, "projects", project)
        deployments = get_deployments(space_id, environment_id, project_id)
        deployment_count = deployment_count + len(deployments)
        for deployment in deployments:
            created = parse_octopus_date(deployment["Created"])
            if earliest_deployment is None or earliest_deployment > created:
                earliest_deployment = created
            if latest_deployment is None or latest_deployment < created:
                latest_deployment = created
    if latest_deployment is not None:
        # return average seconds / deployment from the earliest deployment to now
        return (datetime.now(pytz.utc) - earliest_deployment).total_seconds() / deployment_count
        # You could also return the frequency between the first and last deployment
        # return (latest_deployment - earliest_deployment).total_seconds() / deployment_count
    return None


def get_change_failure_rate():
    releases_with_issues = 0
    deployment_count = 0
    space_id = get_space_id(args.octopus_space)
    environment_id = get_resource_id(space_id, "environments", args.octopus_environment)
    for project in args.octopus_project.split(","):
        project_id = get_resource_id(space_id, "projects", project)
        deployments = get_deployments(space_id, environment_id, project_id)
        deployment_count = deployment_count + len(deployments)
        for deployment in deployments:
            release = get_resource(space_id, "releases", deployment["ReleaseId"])
            for buildInfo in release["BuildInformation"]:
                if len(buildInfo["WorkItems"]) != 0:
                    # Note this measurement is not quite correct. Technically, the change failure rate
                    # measures deployments that result in a degraded service. We're measuring
                    # deployments that included fixes. If you made 4 deployments with issues,
                    # and fixed all 4 with a single subsequent deployment, this logic only detects one
                    # "failed" deployment instead of 4.
                    #
                    # To do a true measurement, issues must track the deployments that introduced the issue.
                    # There is no such out of the box field in GitHub actions though, so for simplicity
                    # we assume the rate at which fixes are deployed is a good proxy for measuring the
                    # rate at which bugs are introduced.
                    releases_with_issues = releases_with_issues + 1
    if releases_with_issues != 0 and deployment_count != 0:
        return releases_with_issues / deployment_count
    return None


def get_change_lead_time_summary(lead_time):
    if lead_time is None:
        print("Change lead time: N/A (no deployments or commits)")
    # One hour
    elif lead_time < 60 * 60:
        print("Change lead time: Elite (Average " + str(round(lead_time / 60 / 60, 2))
              + " hours between commit and deploy)")
    # Every week
    elif lead_time < 60 * 60 * 24 * 7:
        print("Change lead time: High (Average " + str(round(lead_time / 60 / 60 / 24, 2))
              + " days between commit and deploy)")
    # Every six months
    elif lead_time < 60 * 60 * 24 * 31 * 6:
        print("Change lead time: Medium (Average " + str(round(lead_time / 60 / 60 / 24 / 31, 2))
              + " months between commit and deploy)")
    # Longer than six months
    else:
        print("Change lead time: Low (Average " + str(round(lead_time / 60 / 60 / 24 / 31, 2))
              + " months between commit and deploy)")


def get_deployment_frequency_summary(deployment_frequency):
    if deployment_frequency is None:
        print("Deployment frequency: N/A (no deployments found)")
    # Multiple times per day
    elif deployment_frequency < 60 * 60 * 12:
        print("Deployment frequency: Elite (Average " + str(round(deployment_frequency / 60 / 60, 2))
              + " hours between deployments)")
    # Every month
    elif deployment_frequency < 60 * 60 * 24 * 31:
        print("Deployment frequency: High (Average " + str(round(deployment_frequency / 60 / 60 / 24, 2))
              + " days between deployments)")
    # Every six months
    elif deployment_frequency < 60 * 60 * 24 * 31 * 6:
        print("Deployment frequency: Medium (Average " + str(round(deployment_frequency / 60 / 60 / 24 / 31, 2))
              + " months between deployments)")
    # Longer than six months
    else:
        print("Deployment frequency: Low (Average " + str(round(deployment_frequency / 60 / 60 / 24 / 31, 2))
              + " months between commit and deploy)")


def get_change_failure_rate_summary(failure_percent):
    if failure_percent is None:
        print("Change failure rate: N/A (no issues or deployments found)")
    # 15% or less
    elif failure_percent <= 0.15:
        print("Change failure rate: Elite (" + str(round(failure_percent * 100, 0)) + "%)")
    # Interestingly, everything else is reported as High to Low
    else:
        print("Change failure rate: Low (" + str(round(failure_percent * 100, 0)) + "%)")


def get_time_to_restore_service_summary(restore_time):
    if restore_time is None:
        print("Time to restore service: N/A (no issues or deployments found)")
    # One hour
    elif restore_time < 60 * 60:
        print("Time to restore service: Elite (Average " + str(round(restore_time / 60 / 60, 2))
              + " hours between issue opened and deployment)")
    # Every month
    elif restore_time < 60 * 60 * 24:
        print("Time to restore service: High (Average " + str(round(restore_time / 60 / 60, 2))
              + " hours between issue opened and deployment)")
    # Every six months
    elif restore_time < 60 * 60 * 24 * 7:
        print("Time to restore service: Medium (Average " + str(round(restore_time / 60 / 60 / 24, 2))
              + " hours between issue opened and deployment)")
    # Technically the report says longer than six months is low, but there is no measurement
    # between week and six months, so we'll say longer than a week is low.
    else:
        print("Deployment frequency: Low (Average " + str(round(restore_time / 60 / 60 / 24, 2))
              + " hours between issue opened and deployment)")


if args.output == 'text':
    print("DORA stats for project(s) " + args.octopus_project + " in " + args.octopus_environment)
    get_change_lead_time_summary(get_change_lead_time())
    get_deployment_frequency_summary(get_deployment_frequency())
    get_change_failure_rate_summary(get_change_failure_rate())
    get_time_to_restore_service_summary(get_time_to_restore_service())
else:
    dictionary = {
        'lead_time': get_change_lead_time(),
        'deployment_frequency': get_deployment_frequency(),
        'change_failure_rate': get_change_failure_rate(),
        'time_to_restore_service': get_time_to_restore_service()
    }
    print(json.dumps(dictionary, indent=2))
