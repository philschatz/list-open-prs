#!/usr/bin/env python3

from datetime import datetime
import json
import os
import sys
from urllib.request import Request, urlopen


GITHUB_BEARER_TOKEN = os.environ['GITHUB_BEARER_TOKEN']
GITHUB_ENDPOINT = 'https://api.github.com/graphql'
ORGANIZATION = os.environ['ORGANIZATION']
MAX_PR_AGE = int(os.environ.get('MAX_PR_AGE', 31))
DEVELOPERS = {
    # github username: slack userid, slack username
    'karenc': ('<@U0F9C99ST>', '@karen'),
    'pumazi': ('<@U0F988KSQ>', '@mulich'),
    'therealmarv': ('<@U340WT25C>', '@therealmarv'),
    'philschatz': ('<@U0F5LRG3Z>', '@phil'),
    'm1yag1': ('<@U0F55RAAG>', '@mike'),
}
REVIEWERS = {
    'helenemccarron': ('<@U0FU55RRT>', '@hélène'),
    'tomjw64': ('<@U199K9DTJ>', '@Thomas'),
    'brittany-johnson': ('<@U7FHVAJ4T>', '@BrittanyJ'),
}
REVIEWERS.update(DEVELOPERS)


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
                        reviews(last: 50) {
                            nodes {
                                author {
                                    login
                                }
                                state
                                createdAt
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


def to_slack_user(github_username, mention=True):
    if github_username in REVIEWERS:
        if mention:
            return REVIEWERS[github_username][0]
        return REVIEWERS[github_username][1]
    return github_username


def to_datetime(string):
    return datetime.strptime(string, '%Y-%m-%dT%H:%M:%SZ')


def to_days_ago(date, today=datetime.today()):
    return (today - date).days


class PullRequest:
    @classmethod
    def from_api(cls, **struct):
        self = cls()
        self.reviews = Review.from_api(self, struct['author']['login'],
                                       **struct.pop('reviews'))
        self.review_requests = ReviewRequest.from_api(
            **struct.pop('reviewRequests'))
        struct['createdAt'] = to_datetime(struct['createdAt'])
        struct['updatedAt'] = to_datetime(struct['updatedAt'])
        self.fields = struct
        self.age = to_days_ago(self.fields['updatedAt'])
        self.should_display = self.age < MAX_PR_AGE and \
            self.fields['author']['login'] in DEVELOPERS
        return self

    def newer_than(self, time):
        return self.fields['updatedAt'] > time

    def display_author(self):
        return to_slack_user(self.fields['author']['login'],
                             mention=self.author_actionable())

    def author_actionable(self):
        return self.fields['title'].startswith('WIP') or (
            not self.review_requests and
            not any(r.pending() for r in self.reviews))

    def __str__(self):
        s = """\
{user} submitted {repo_name} "{title}", updated {age} ago:
    - {url}
""".format(user=self.display_author(),
           repo_name=self.fields['repo_name'],
           title=self.fields['title'],
           age=(self.age == 1 and '1 day' or '{} days'.format(self.age)),
           url=self.fields['url'])
        if self.reviews:
            s += '    - Reviewed by: {}\n'.format(
                ', '.join(str(r) for r in self.reviews))
        s += '    - Pending reviews from: {}'.format(
            ', '.join(str(r) for r in self.review_requests) or 'N/A')
        return s


class Review:
    @classmethod
    def from_api(cls, pull_request, pull_request_author, **struct):
        states = {}
        created_at = {}
        results = []
        for r in struct['nodes']:
            author = r['author']['login']
            if author == pull_request_author:
                continue
            if states.get(author, 'COMMENTED') == 'COMMENTED':
                states[author] = r['state']
            if r['createdAt'] > created_at.get(author, ''):
                created_at[author] = r['createdAt']
        for author in states:
            self = cls()
            results.append(self)
            self.fields = {
                'author': author,
                'createdAt': to_datetime(created_at[author]),
                'state': states[author],
            }
            self.pull_request = pull_request
        return results

    def pending(self):
        return self.fields['state'] != 'APPROVED' and \
            self.pull_request.newer_than(self.fields['createdAt']) and \
            not self.pull_request.fields['title'].startswith('WIP')

    def __str__(self):
        if self.pending():
            user = to_slack_user(self.fields['author'])
        else:
            user = to_slack_user(self.fields['author'], mention=False)
        return '{} ({})'.format(user, self.fields['state'])


class ReviewRequest:
    @classmethod
    def from_api(cls, **struct):
        results = []
        for r in struct['nodes']:
            results.append(cls())
            results[-1].fields = r
        return results

    def __str__(self):
        return to_slack_user(self.fields['requestedReviewer']['login'])


prs = []
for repo in get_open_prs(ORGANIZATION, 'OPEN'):
    for pull_request in repo['pullRequests']:
        pr = PullRequest.from_api(repo_name=repo['name'], **pull_request)
        if pr.should_display:
            prs.append(pr)

prs.sort(key=lambda a: a.age)
for pr in prs:
    print(str(pr))
