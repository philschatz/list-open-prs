#!/usr/bin/env python3

from datetime import datetime
import json
import os
import sys
from urllib.request import Request, urlopen


GITHUB_BEARER_TOKEN = os.environ['GITHUB_BEARER_TOKEN']
GITHUB_ENDPOINT = 'https://api.github.com/graphql'
ORGANIZATION = os.environ['ORGANIZATION']


def query_github(query):
    req = Request(GITHUB_ENDPOINT, method='POST',
                  data=json.dumps({'query': query}).encode('utf-8'),
                  headers={'Authorization': 'bearer {}'.format(
                      GITHUB_BEARER_TOKEN)})
    content = json.loads(urlopen(req).read().decode('utf-8'))
    if 'errors' in content:
        sys.stderr.write('{}\n'.format(query))
        raise RuntimeError('Error when querying github: {}'.format(content))
    return content


def get_open_prs(org, states):
    query = """\
query {
    organization(login: "%s") {
        repositories(orderBy: { field: UPDATED_AT, direction: DESC }
                     first: 100) {
            nodes {
                name
                pullRequests(states: %s
                             first: 20
                             orderBy: { field: UPDATED_AT, direction: DESC }) {
                    nodes {
                        url
                        title
                        createdAt
                        updatedAt
                        author {
                            login
                        }
                        reviews(first: 50) {
                            nodes {
                                author {
                                    login
                                }
                                state
                            }
                        }
                        reviewRequests(first: 10) {
                            nodes {
                                requestedReviewer {
                                    ... on User {
                                        login
                                    }
                                }
                            }
                        }
                    }
                }
            }
            pageInfo {
                endCursor
                hasNextPage
            }
        }
    }
}
"""
    result = query_github(query % (org, states))['data']['organization'][
        'repositories']['nodes']
    for repo in result:
        if repo['pullRequests']['nodes']:
            yield {
                'name': repo['name'],
                'pullRequests': repo['pullRequests']['nodes'],
            }


def to_slack_user(github_username):
    return REVIEWERS.get(github_username, github_username)


DEVELOPERS = {
    # github username: slack userid
    'karenc': '<@U0F9C99ST>', # karen
    'pumazi': '<@U0F988KSQ>', # mulich
    'therealmarv': '<@U340WT25C>', # therealmarv
    'philschatz': '<@U0F5LRG3Z>', # phil
    'm1yag1': '<@U0F55RAAG>', # mike
}
REVIEWERS = {
    'helenemccarron': '<@U0FU55RRT>', # hélène
    'tomjw64': '<@U199K9DTJ>', # Thomas
    'brittany-johnson': '<@U7FHVAJ4T>', # BrittanyJ
}
REVIEWERS.update(DEVELOPERS)


prs = []
today = datetime.today()
for repo in get_open_prs(ORGANIZATION, 'OPEN'):
    for pr in repo['pullRequests']:
        updatedAt = datetime.strptime(pr['updatedAt'], '%Y-%m-%dT%H:%M:%SZ')
        createdAt = datetime.strptime(pr['createdAt'], '%Y-%m-%dT%H:%M:%SZ')
        author = pr['author']['login']
        age = (today - updatedAt).days
        if author in DEVELOPERS and age < 31:
            reviewers = {}
            for r in pr['reviews']['nodes']:
                if r['author']['login'] == author:
                    continue
                reviewer = to_slack_user(r['author']['login'])
                if reviewers.get(reviewer, 'COMMENTED') == 'COMMENTED':
                    reviewers[reviewer] = r['state']
            requested_reviewers = set([
                to_slack_user(r['requestedReviewer']['login'])
                for r in pr['reviewRequests']['nodes']
                if r['requestedReviewer']['login'] != author])
            prs.append({
                'user': DEVELOPERS[author],
                'title': pr['title'],
                'age': age == 1 and '1 day' or '{} days'.format(age),
                'url': pr['url'],
                'reviewers': ', '.join([
                    '{} ({})'.format(*item) for item in reviewers.items()]),
                'requested_reviewers': ', '.join(
                    requested_reviewers - reviewers.keys()) or 'N/A',
                'repo_name': repo['name'],
            })

prs.sort(key=lambda a: a['age'])
for pr in prs:
    print("""\
{user} submitted {repo_name} "{title}", updated {age} ago:
    - {url}""".format(**pr))
    if pr.get('reviewers'):
        print('    - Reviewed by: {reviewers}'.format(**pr))
    if pr.get('requested_reviewers'):
        print('    - Pending reviews from: {requested_reviewers}'.format(
            **pr))
