#!/usr/bin/env python
# -*- coding: utf-8 -*-

import flask
import jira
import settings
import re
import requests
import json

# some aliasses
request = flask.request
Response = flask.Response
json = flask.json

app = flask.Flask(__name__)

jira_url_http = settings.JIRA_URL.replace( 'https://', 'http://' )
jira_url_https = settings.JIRA_URL.replace( 'http://', 'https://' )

@app.route('/', methods=['POST'])
def receive_mattermost():
    """We only have 1 incoming hook"""
    try:
        form = request.form
        token = form.getlist('token')[0]
        fromChannel = form.getlist('channel_name')[0]
        userName = form.getlist('user_name')[0]
        requestText = form.getlist('text')[0]
        requestUserid = form.getlist('user_id')[0]
        userIcon = settings.MATTERMOST_URL+'/api/v4/users/'+requestUserid+'/image'
    except:
        app.logger.error('Something went wrong when initializing the parameters.')
        return send_message_back( get_error_payload( fromChannel, requestText, userName, userIcon, "The integration is not correctly set up. Token not valid." ) )

    if settings.MATTERMOST_TOKEN:
        if not token == settings.MATTERMOST_TOKEN:
            app.logger.error('Received wrong token, received [%s]', token)
            return send_message_back( get_error_payload( fromChannel, requestText, userName, userIcon, "The integration is not correctly set up. Token not valid." ) )

    issue_ids = search_token(requestText)

    if issue_ids is None:
        return send_message_back( get_error_payload( fromChannel, requestText, userName, userIcon, "Could not identify a jira issue ID." ) )
    
    unique_issue_ids = set( issue_ids )
    requestTextWithLinks = replaceIssueIdWithLink( requestText, unique_issue_ids )

    payload = get_detail_from_jira( unique_issue_ids, fromChannel, userName, requestTextWithLinks, userIcon )

    if payload is None:
        return send_message_back( get_error_payload( fromChannel, requestText, userName, userIcon, "There was an exception when searching for the issue in Jira." ) )

    return send_message_back( payload )

def send_message_back( payload ):
    resp = Response(
		json.dumps( payload ),
        status=200,
        mimetype='application/json')
    return resp

def search_token(text):
    """Search in the provided text for a match on the regexp, and return"""
    matches = re.findall('(%s)' % settings.TICKET_REGEXP, text)
    if matches:
        return matches
    else:
        return None

def replaceIssueIdWithLink( requestText, issue_ids ):
    returnString = requestText
    for issue_id in issue_ids:
        returnString = remove_jira_url_from_issue( returnString, issue_id )
        returnString = returnString.replace( issue_id, '['+issue_id+']('+ get_url( issue_id ) +')' )
    return returnString
	

def parse_icon_name(field):
    """Return a 'nice' formatter layout for icons and text"""
    return \
        '![](' + \
        field.iconUrl + ') ' +\
        field.name
		
def get_url( issue_id ):
    return get_full_url( issue_id, settings.JIRA_URL )

def get_full_url( issue_id, url ):
    return '%s/browse/%s' % ( url, issue_id)

def remove_jira_url_from_issue( text, issue_id ):
    returnText = text.replace( get_full_url( issue_id, jira_url_http ), issue_id )
    returnText = returnText.replace( get_full_url( issue_id, jira_url_https ), issue_id )
    return returnText

def get_color_for_issue(issue_status):
    """Return the color matching the issue status in jira"""
    return '%s/browse/%s' % (settings.JIRA_URL, ticket_id)

def get_error_payload( channel, text, user, icon, errorMessage ):
    """Return the payload of the return message in case of an error"""
    return { 'response_type': 'ephemeral', 'channel': channel, 'text': 'The message has not been sent.', 'username': 'Jira Issue', 
	          'attachments': [{
                    'fallback': 'There was a problem with the Jira bot.',
                    'color': settings.ERROR_COLOR,
		            'text': text,
					'fields': [
					    {
						  'short': False,
						  'title': 'Reason:',
						  'value': errorMessage
						}
				     ]
                  }]
				}


def get_detail_from_jira( issue_ids, fromChannel, userName, requestText, userIcon ):
    """Connect to JIRA and retrieve the details"""

    issues_attachments = []
	
    for issue_id in issue_ids:
        try:
            jc = jira.JIRA(server=settings.JIRA_URL,
                           basic_auth=(settings.JIRA_USER, settings.JIRA_PASS))
        except jira.JIRAError:
            app.logger.error('Could not connect to JIRA', exc_info=True)
            return get_error_payload( fromChannel, requestText, userName, userIcon, 'Could not connect to JIRA.')

        try:
            issues = jc.search_issues('key=%s' % issue_id)
        except jira.JIRAError as e:
            app.logger.error('Search on JIRA failed', exc_info=True)
            return get_error_payload( fromChannel, requestText, userName, userIcon, 'Search on JIRA failed.\nError message: '+e.text)

        if not len(issues):
            return get_error_payload( fromChannel, requestText, userName, userIcon, 'Could not find a matching ticket for %s' % (ticked_id))
		
        issue = issues[0]

        issueTitle = '[%s - %s](%s "%s")' % (issue_id, issue.fields.summary, get_url(issue_id), issue_id)
        assignee = (issue.fields.assignee.displayName if issue.fields.assignee else 'Nobody')
        issueType = parse_icon_name(issue.fields.issuetype)
        issueStatus = parse_icon_name(issue.fields.status)
        issueDescription = issue.fields.description
        if issueDescription is None:
            issueDescription = '_~ No description for this issue ~_'

        formattedTitle = '#### ![](%s) [%s &nbsp;&nbsp;&nbsp; %s](%s "%s") ####' % (issue.fields.issuetype.iconUrl, issue_id, issue.fields.summary, get_url(issue_id), issue_id)
        colorForIssue = settings.COLORS_DICTONARY.get( issue.fields.status.name, '' )
        formattedText = formattedTitle +'\n'+issueDescription
		
        attachment = {
                        'fallback': 'Jira issue posted.',
                        'color': colorForIssue,
		                'text': formattedText,
		                'fields': [
                            {
                                "short": True,
                                "title": "Type",
                                "value": issueType
                            },
                            {
                                "short": True,
                                "title": "Status",
                                "value": issueStatus
                            },
                            {
                                "short": False,
                                "title": "Assignee",
                                "value": assignee
                            }
                        ],
                    }
        issues_attachments.append( attachment )


    payload = {'response_type': 'in_channel', 'channel': fromChannel, 'text': requestText, 'username': userName,
                    'icon_url': userIcon,
	                'attachments': issues_attachments
	              }

    return payload


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)

# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4
