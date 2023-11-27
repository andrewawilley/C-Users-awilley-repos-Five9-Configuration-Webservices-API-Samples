import base64
import code

import argparse
from lxml import etree
# import os
import requests
import zeep
from zeep.plugins import HistoryPlugin

from private.credentials import ACCOUNTS


class Five9ClientCreationError(Exception):
    pass


class Five9Client(zeep.Client):
    call_counters = None
    history = None

    def __init__(self, *args, **kwargs):
        five9username = kwargs.get("five9username", None)
        five9password = kwargs.get("five9password", None)
        account = kwargs.get("account", None)
        api_hostname = kwargs.get("api_hostname", "api.five9.com")
        api_version = kwargs.get("api_version", "v12")

        self.history = HistoryPlugin()

        # url and user settings consolidated here for convenience to use later
        api_definition_base = "https://{api_hostname}/wsadmin/{api_version}/?wsdl&user={five9username}"

        if five9username == None and five9password == None:
            # Target the desired account using the alias in private.credentials
            api_account_alias = account or "default_account"
            api_account = ACCOUNTS.get(api_account_alias, {})
            if api_account == {} or api_account.get("username" or None) == "apiUserUsername":
                five9username = input("Five9 Username: ")
                five9password = input("Five9 Password: ")
            else:
                five9username = api_account.get("username", None)
                five9password = api_account.get("password", None)

        # prepare the session with BasicAuth headers
        self.transport_session = requests.Session()
        self.transport_session.auth = requests.auth.HTTPBasicAuth(five9username, five9password)

        self.api_definition = api_definition_base.format(
            api_hostname=api_hostname, api_version=api_version, five9username=five9username
        )
        print(self.api_definition)

        # BREAKFIX - Get the directory of the current file and construct the WSDL file path
        # current_dir = os.path.dirname(os.path.realpath(__file__))
        # wsdl_file_path = os.path.join(current_dir, 'static_resources', 'config_webservices_v13.wsdl')

        try:
            super().__init__(
                self.api_definition,
                transport=zeep.Transport(session=self.transport_session),
                plugins=[self.history],
            )
            # super().__init__(
            #     wsdl_file_path,
            #     transport=zeep.Transport(session=self.transport_session),
            #     plugins=[self.history],
            # )
            self.call_counters = self.service.getCallCountersState()
            
            print(f"Client ready for {five9username}")

        # handle generic http errors
        except (requests.exceptions.HTTPError, requests.exceptions.ConnectionError, zeep.exceptions.Fault) as e:
            # pass the error to the caller through the Five9ClientCreationError exception
            raise Five9ClientCreationError(e)


    def __format_envelope(self, envelope):
        """
        Formats the SOAP envelope for printing.

        Args:
            envelope: The SOAP envelope to format.

        Returns:
            A formatted string containing the SOAP envelope.
        """
        return etree.tostring(envelope, encoding="unicode", pretty_print=True)


    @property
    def latest_envelopes(self):
        """
        Returns the latest SOAP envelopes that were sent or received by the client as a string.

        Returns:
            A string containing the latest SOAP envelopes that were sent or received by the client.
            If no envelopes are available, an empty string is returned.
        """
        envelopes = ""
        try:
            for hist in [self.history.last_sent, self.history.last_received]:
                e = etree.tostring(
                    hist["envelope"], encoding="unicode", pretty_print=True
                )
                envelopes += e + "\n\n"
            return envelopes
        except (AttributeError, IndexError, TypeError):
            # catch cases where the history object was altered to an invalid type
            # re-initialize the history object
            envelopes = "History object not found.  Re-initializing the history object.\n\n"
            self.history = HistoryPlugin()

            return envelopes

    @property
    def latest_envelope_sent(self):
        """
        Returns the latest SOAP envelope that was sent by the client as a string.

        Returns:
            A string containing the latest SOAP envelope that was sent by the client.
            If no envelope is available, an empty string is returned.
        """
        try:
            return self.__format_envelope(self.history.last_sent["envelope"])
        except (AttributeError, IndexError, TypeError):
            # catch cases where the history object was altered to an invalid type
            # re-initialize the history object
            self.history = HistoryPlugin()

            return ""

    @property    
    def latest_envelope_received(self):
        """
        Returns the latest SOAP envelope that was received by the client as a string.

        Returns:
            A string containing the latest SOAP envelope that was received by the client.
            If no envelope is available, an empty string is returned.
        """
        try:
            return self.__format_envelope(self.history.last_received["envelope"])
        except (AttributeError, IndexError, TypeError):
            # catch cases where the history object was altered to an invalid type
            # re-initialize the history object
            self.history = HistoryPlugin()

            return ""

    @property
    def current_api_useage_formatted(self):
        # Fetching the current state of call counters
        current_call_counters = self.service.getCallCountersState()
        
        # Initialize an empty dictionary to store the results
        result = {}

        # Iterate over each object in the call counter state
        for obj in current_call_counters:
            timeout = obj['timeout']

            # Iterate over each state in the callCounterStates of the current object
            for state in obj['callCounterStates']:
                operation_type = state['operationType']

                # If the operation type has not been added to the result dictionary, add it with an empty list as its value
                if operation_type not in result:
                    result[operation_type] = []

                # Format the usage as a tuple where the first element is the timeout and the second element is a formatted string
                usage = (timeout, f"{timeout: >5}: {state['value']: >7}/{state['limit']}")
                
                # Add the formatted usage to the list of usages for the current operation type
                result[operation_type].append(usage)
            
        # Sort the dictionary by keys (operation types)
        result = dict(sorted(result.items()))

        # Initialize a list to store the formatted output
        formatted_output = []

        # Iterate over each operation type and its associated usages
        for operation_type, usages in result.items():
            usages.sort()  # Sorting the list of usages
            # Format the output string for the current operation type and add it to the list of formatted outputs
            formatted_output.append("{}:\n{}".format(operation_type, "\n".join(["\t"+u[1] for u in usages])))

        # Join the list of formatted outputs into a single string with two newlines between each section
        return "\n\n".join(formatted_output)



    @property
    def latest_request_headers(self):
        """
        Prints the latest request with headers and body.
        """
        last_request = self.history.last_sent
        request_string = ""
        if last_request:
            headers = last_request["http_headers"]

            for key, value in headers.items():
                request_string += f"{key}: {value}\n"

            # Print Basic Auth header
            auth = f"{self.transport_session.auth.username}:{self.transport_session.auth.password}"
            # base64 encode the username and password from the session
            auth_header_value = base64.b64encode(auth.encode("utf-8")).decode("utf-8")

            if auth_header_value:
                request_string += f"Authorization: {auth_header_value}"
            
            return request_string

        else:
            return "No request found in history"

    # TODO class method to obtain the domain rate limits to update a class property
    # that helps bake in a delay between requests if needed


    def print_available_service_methods(self, print_methods=True):
        """
        Prints the available methods for the client.
        """
        print("Available methods:")
        # create sorted list of methods from the service
        methods = sorted(self.service._operations.keys())
        for method in methods:
            print(f"\t{method}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-u",
        "--username",
        help="Five9 Username for authentication, password argument required if provided",
        required=False,
    )
    parser.add_argument(
        "-p",
        "--password",
        help="Five9 Password for authentication, username argument required if provided",
        required=False,
    )
    parser.add_argument(
        "-a",
        "--account",
        help="Alias for credential stored in private/credentials",
        required=False,
    )

    parser.add_argument(
        "-go",
        "--getobjects",
        action="store_true",
        help="preload common domain objects",
    )

    args = vars(parser.parse_args())
    username = args["username"] or None
    password = args["password"] or None
    account = args["account"] or None
    get_objects = args["getobjects"] or None
    client = Five9Client(five9username=username, five9password=password, account=account)

    if get_objects:
        users = client.service.getUsersInfo()
        print("\nUsers loaded as 'users'")
        campaigns = client.service.getCampaigns()
        print("Campaigns loaded as 'campaigns'")
        skills = client.service.getSkills()
        print("Skills loaded as 'skills'\n")
    print()
    code.interact(local=locals())
