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
                             first: 100
                             orderBy: { field: UPDATED_AT, direction: DESC }) {
                    nodes {
                        url
                        title
                        createdAt
                        updatedAt
                        author {
                            login
                        }
                        reviews(first: 10) {
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


def format_reviewer(github_username):
    if github_username in REVIEWERS:
        return '@{}'.format(REVIEWERS[github_username])
    return github_username


DEVELOPERS = {
    # github username: slack username
    'karenc': 'karen',
    'pumazi': 'mulich',
    'therealmarv': 'therealmarv',
    'philschatz': 'phil',
    'm1yag1': 'mike',
}
REVIEWERS = {
    'helenemccarron': 'hélène',
    'tomjw64': 'Thomas',
    'brittany-johnson': 'BrittanyJ',
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
        reviewers = {
            format_reviewer(r['author']['login']): r['state']
            for r in pr['reviews']['nodes']}
        requested_reviewers = set([
            format_reviewer(r['requestedReviewer']['login'])
            for r in pr['reviewRequests']['nodes']])
        if author in DEVELOPERS and age < 31:
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
@{user} submitted {repo_name} "{title}", updated {age}:
    - {url}""".format(**pr))
    if pr.get('reviewers'):
        print('    - Reviewed by: {reviewers}'.format(**pr))
    if pr.get('requested_reviewers'):
        print('    - Pending reviewers from: {requested_reviewers}'.format(
            **pr))
