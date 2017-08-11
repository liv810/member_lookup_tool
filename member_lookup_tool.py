import sys, subprocess, os
import re, json, ast
import urllib

import flask
import jinja2 # for HTML formatting

# API Keys for NationBuilder and ActionKit
NB_ACCESS_TOKEN = "SECRET_KEY"
actionkit_api_prefix = "curl -i -u SECRET_KEY"

# Create the Flask application.
APP = flask.Flask(__name__)

def api_call(cmd):
	"""
	Makes a call to an API via a specified bash command, cmd.
	Returns a JSON object with the API output.
	"""
	process = subprocess.Popen(cmd.split(), stdout=subprocess.PIPE)
	output, error = process.communicate()
	return output

def split_json(str_to_parse, index=0):
	"""
	Takes in a string and outputs the index-th {}-surrounded string.
	"""
	return re.findall('{.*}', str_to_parse)[index]

def get_json_property(json, property, default_val=''):
        """
        Retrieve a property of a json object, else return default_val.
        """
	if property in json:
		return str(json[property])
	else:
		return default_val


def get_email_given_name(first_name, last_name):
	""" Given a first name and last name, get the email address
	for that person using ActionKit.
	"""
	actionkit_api_suffix = "/rest/v1/user/?"+urllib.urlencode({'last_name':last_name})
	actionkit_output = json.loads(split_json(api_call(actionkit_api_prefix+actionkit_api_suffix)))['objects']
	# If a first name was provided, then filter to the one with the correct first name.
	if first_name:
		offset = 100
		while len(actionkit_output) > 0:
			actionkit_output = [x for x in actionkit_output if x['first_name'] == first_name]
			if len(actionkit_output) > 0: # We found a matching first name
				break
			else: # Go through the next load of people with that last name	
				actionkit_output = json.loads(split_json(api_call(actionkit_api_prefix+actionkit_api_suffix+
					                          '&_limit=100&_offset=%d' % offset)))['objects']
				offset += 100
	if len(actionkit_output) == 0: # Then no person matches this first name and last name pair.
		return []
	else:
		return [get_json_property(x,'email') for x in actionkit_output]

def parse_actionkit(email):
        """ Given an email address, this function constructs a list of
        tuples with their user characteristics from ActionKit.
        """
	actionkit_api_suffix = "/rest/v1/user/?"+urllib.urlencode({'email': email})
	actionkit_output = json.loads(split_json(api_call(actionkit_api_prefix+actionkit_api_suffix)))['objects'][0]
	fields = []
	fields.append(("Name", "%s %s" % (get_json_property(actionkit_output,'first_name'), get_json_property(actionkit_output,'last_name'))))
	fields.append(("Email", get_json_property(actionkit_output,'email')))
	fields.append(("Address", get_json_property(actionkit_output,'address1')))
	fields.append(("City", "%s, %s %s" % (get_json_property(actionkit_output,'city'), get_json_property(actionkit_output,'state'), get_json_property(actionkit_output,'zip'))))
	if len(actionkit_output['phones']) > 0:
		actionkit_phone_output = json.loads(split_json(api_call(actionkit_api_prefix + actionkit_output['phones'][0])))
		fields.append(("Phone", actionkit_phone_output['normalized_phone']))
	fields.append(())
    fields.append(("Signup date", get_json_property(actionkit_output,'created_at')))
	fields.append(("Subscription status", get_json_property(actionkit_output,'subscription_status')))
    fields.append(())

	# Parse donation history
    actionkit_order_output = json.loads(split_json(api_call(actionkit_api_prefix + actionkit_output['orders'])))['objects']
    completed_orders = [x for x in actionkit_order_output if get_json_property(x,'status')=='completed']
	donation_times = [str(x['created_at']) for x in completed_orders]
	
	actionkit_order_recurrings_output = json.loads(split_json(api_call(actionkit_api_prefix + actionkit_output['orderrecurrings'])))['objects']
	completed_recurring_orders = [x for x in actionkit_order_recurrings_output if get_json_property(x,'status')=='completed']
	donation_times += [str(x['created_at']) for x in completed_recurring_orders]

	if len(donation_times) > 0:
		fields.append(("Has donated", "True"))
		fields.append(("    # of non-recurring donations", "%d" % len(completed_orders)))
		fields.append(("    Non-recurring donation total", "%.2f" % sum([float(x['total']) for x in completed_orders])))
		fields.append(("    # of recurring donations", "%d" % len(completed_recurring_orders)))
		fields.append(("    Recurring donation total", "%.2f" % sum([float(x['amount']) for x in completed_recurring_orders])))
		fields.append(("    Last donation", max(donation_times)))
	else:
		fields.append(("Has donated", "False"))

	fields.append(("ActionKit user link", "SECRET_URL/%s" % get_json_property(actionkit_output, 'id')))
        fields.append(("ActionKit actions link", "SECRET_URL/%s/actionhistory" % get_json_property(actionkit_output, 'id')))
        fields.append(())
	return fields

def parse_nationbuilder(email):
        """ Given an email address, this function constructs a list of
        tuples with their user characteristics from NationBuilder.
        """
	nationbuilder_api_call = "curl SECRET_URL/api/v1/people/match?"+urllib.urlencode({'email':email})+"&access_token="+NB_ACCESS_TOKEN
	fields = []
	nationbuilder_output = json.loads(split_json(api_call(nationbuilder_api_call)))
	if 'person' not in nationbuilder_output.keys(): # Then this email doesn't have a nationbuilder user associated with it.
		return fields
	else:
		nationbuilder_output = nationbuilder_output['person']
	fields.append(("Is volunteer", get_json_property(nationbuilder_output,'is_volunteer')))
	fields.append(("Chapter involvement", str([str(x) for x in nationbuilder_output['tags'] if 'hapter' in x])))
	fields.append(("NationBuilder user link", "SECRET_URL/%s" % \
		get_json_property(nationbuilder_output, 'id')))
	return fields

def parse_final_output(email):
	# Combines ActionKit and NationBuilder output into a single list of (characteristic, value) tuples.
	fields = parse_actionkit(email)
	fields += parse_nationbuilder(email)
	return fields

@APP.route('/member_lookup_tool/')
def index():
    """ Displays the index page accessible at '/member_lookup_tool/'
    """
    first_name = flask.request.args.get('first_name')
    last_name = flask.request.args.get('last_name')
    email = flask.request.args.get('email')
    # If an email address was not provided, then find the email for the provided name.
    if (first_name and last_name) and (not email):
    	emails = get_email_given_name(first_name, last_name)
    	if len(emails) == 0:
    		return flask.render_template('output.html', output=None)
    	elif len(emails) == 1:
    		email = emails[0]
    	else:
    		return flask.render_template('disambiguate_email.html', emails=emails)
    # Render the output for that email address.
    if email:
    	return flask.render_template('output.html', output = parse_final_output(email))
    # If none of the specified parameters were given, return the blank form.
    else:
    	return flask.render_template('index.html')

if __name__ == '__main__':
    # APP.debug = True
    APP.run()
