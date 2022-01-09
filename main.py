import os
import sys
from datetime import datetime
from functools import cmp_to_key
from requests.auth import HTTPBasicAuth
import tempfile
from requests import get
import zipfile
import argparse

parser = argparse.ArgumentParser(description='Scan a deployment for a dependency.')
parser.add_argument('--octopusUrl', dest='octopus_url', action='store', help='The Octopus server URL',
                    required=True)
parser.add_argument('--octopusApiKey', dest='octopus_api_key', action='store', help='The Octopus API key',
                    required=True)
parser.add_argument('--githubUser', dest='github_user', action='store', help='The GitHub username',
                    required=True)
parser.add_argument('--githubToken', dest='github_token', action='store', help='The GitHub token/password',
                    required=True)
parser.add_argument('--octopusSpace', dest='octopus_space', action='store', help='The Octopus space',
                    required=True)
parser.add_argument('--octopusProject', dest='octopus_project', action='store',
                    help='A comma separated list of Octopus projects', required=True)
parser.add_argument('--octopusEnvironment', dest='octopus_environment', action='store', help='The Octopus environment',
                    required=True)

args = parser.parse_args()

headers = {"X-Octopus-ApiKey": args.octopus_api_key}
github_auth = HTTPBasicAuth(args.github_user, args.github_token)


def compare_dates(date1, date2):
    # Python 3.6 doesn't handle the colon in the timezone of a string like "2022-01-04T04:23:02.941+00:00".
    # So we need to manually strip it out.
    date1_parsed = datetime.strptime(date1["Created"][:-3] + date1["Created"][-2:], '%Y-%m-%dT%H:%M:%S.%f%z')
    date2_parsed = datetime.strptime(date2["Created"][:-3] + date2["Created"][-2:], '%Y-%m-%dT%H:%M:%S.%f%z')
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


def get_earliest_commit_date(release):
    return None


def get_change_lead_time(release):
    return None


def release_has_critical_issue(release):
    return None


def get_average_critical_issue_open_time():
    return None


def parse_github_date(date_string):
    if date_string is None:
        return None
    return datetime.strptime(date_string.replace("Z", "+0000"), '%Y-%m-%dT%H:%M:%S%z')


def parse_octopus_date(date_string):
    if date_string is None:
        return None
    return datetime.strptime(date_string[:-3] + date_string[-2:], '%Y-%m-%dT%H:%M:%S.%f%z')


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
                    closed_date = parse_github_date(commit_response.json()["closed_at"])
                    if closed_date is not None:
                        restore_service_times.append(deployment_date - closed_date)
    if len(restore_service_times) != 0:
        return sum(restore_service_times) / len(restore_service_times)
    return 0


def get_deployment_frequency():
    earliest_deployment = None
    latest_deployment = None
    space_id = get_space_id(args.octopus_space)
    environment_id = get_resource_id(space_id, "environments", args.octopus_environment)
    for project in args.octopus_project.split(","):
        project_id = get_resource_id(space_id, "projects", project)
        deployments = get_deployments(space_id, environment_id, project_id)
        for deployment in deployments:
            created = parse_octopus_date(deployment["Created"])
            if earliest_deployment is None or earliest_deployment > created:
                earliest_deployment = created
            if latest_deployment is None or latest_deployment < created:
                latest_deployment = created
    if latest_deployment is not None:
        # return average seconds / deployment
        return (latest_deployment - earliest_deployment).total_seconds() / len(deployments)
    return None


def get_change_failure_rate():
    releases_with_issues = 0
    space_id = get_space_id(args.octopus_space)
    environment_id = get_resource_id(space_id, "environments", args.octopus_environment)
    for project in args.octopus_project.split(","):
        project_id = get_resource_id(space_id, "projects", project)
        deployments = get_deployments(space_id, environment_id, project_id)
        for deployment in deployments:
            earliest_commit = None
            release = get_resource(space_id, "releases", deployment["ReleaseId"])
            for buildInfo in release["BuildInformation"]:
                if len(buildInfo["WorkItems"]) != 0:
                    ++releases_with_issues
    if len(deployments) != 0:
        return releases_with_issues / len(deployments)
    return 0


def get_change_lead_time_summary(lead_time):
    # One hour
    if lead_time < 60 * 60:
        sys.stdout.write("Change lead time: Elite (hourly)\n")
    # Every week
    elif lead_time < 60 * 60 * 24 * 7:
        sys.stdout.write("Change lead time: High (weekly)\n")
    # Every six months
    elif lead_time < 60 * 60 * 24 * 31 * 6:
        sys.stdout.write("Change lead time: Medium (six monthly)\n")
    # Longer than six months
    else:
        sys.stdout.write("Change lead time: Low (longer than six months)\n")


def get_deployment_frequency_summary(deployment_frequency):
    # Every day
    if deployment_frequency < 60 * 60 * 24:
        sys.stdout.write("Deployment frequency: Elite (daily)\n")
    # Every month
    elif deployment_frequency < 60 * 60 * 24 * 31:
        sys.stdout.write("Deployment frequency: High (monthly)\n")
    # Every six months
    elif deployment_frequency < 60 * 60 * 24 * 31 * 6:
        sys.stdout.write("Deployment frequency: Medium (six monthly)\n")
    # Longer than six months
    else:
        sys.stdout.write("Deployment frequency: Low (more than every six months)\n")


def get_change_failure_rate_summary(failure_percent):
    # 15% or less
    if failure_percent <= 0.15:
        sys.stdout.write("Change failure rate: Elite (<= 15%)\n")
    # Interestingly, everything else is reported as High to Low
    else:
        sys.stdout.write("Change failure rate: Low (> 15%)\n")


def get_deployment_frequency_summary(restore_time):
    # One hour
    if restore_time < 60 * 60 * 24:
        sys.stdout.write("Time to restore service: Elite (hour or less)\n")
    # Every month
    elif restore_time < 60 * 60 * 24:
        sys.stdout.write("Time to restore service: High (day or less)\n")
    # Every six months
    elif restore_time < 60 * 60 * 24 * 7:
        sys.stdout.write("Time to restore service: Medium (week or less)\n")
    # Technically the report says longer than six months is low, but there is no measurement
    # between week and six months, so we'll say longer than a week is low.
    else:
        sys.stdout.write("Deployment frequency: Low (longer than week)\n")


sys.stdout.write("DORA stats for project(s) " + args.octopus_project + " in " + args.octopus_environment + "\n")
get_change_lead_time_summary(get_change_lead_time())
get_deployment_frequency_summary(get_deployment_frequency())
get_change_failure_rate_summary(get_change_failure_rate())
get_deployment_frequency_summary(get_time_to_restore_service())