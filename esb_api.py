"""ESB Smart Meter API wrapper."""
import requests
from random import randint
from time import sleep
from bs4 import BeautifulSoup
import re
import json
import csv
import logging
from datetime import datetime, timedelta
import os

_LOGGER = logging.getLogger(__name__)

# Set to True to use cached data during development
DEBUG_USE_CACHE = os.getenv('ESB_DEBUG_CACHE', 'false').lower() == 'true'
CACHE_FILE = '/config/esb_cache.json'

class ESBSmartMeter:
    """Class to interact with ESB Smart Meter data."""

    def __init__(self, mprn: str, email: str, password: str):
        """Initialize the API wrapper."""
        self.mprn = mprn
        self.email = email
        self.password = password
        self.user_agent = "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:142.0) Gecko/20100101 Firefox/142.0"

    def get_usage_data(self):
        """Get electricity usage data from ESB Networks."""

        # Check if we should use cached data
        if DEBUG_USE_CACHE and os.path.exists(CACHE_FILE):
            _LOGGER.info("Using cached ESB data (DEBUG_USE_CACHE=true)")
            try:
                with open(CACHE_FILE, 'r') as f:
                    cached = json.load(f)
                    _LOGGER.info(f"Loaded {len(cached.get('readings', []))} readings from cache")
                    return cached
            except Exception as e:
                _LOGGER.warning(f"Failed to load cache, fetching fresh data: {e}")

        _LOGGER.info("Fetching fresh data from ESB Networks...")
        session = requests.Session()
        session.headers.update({'User-Agent': self.user_agent})

        try:
            # REQUEST 1 - Initial page load
            _LOGGER.info("Fetching ESB login page...")
            request_1_response = session.get('https://myaccount.esbnetworks.ie/',
                                             allow_redirects=True, timeout=(10, 5))

            result = re.findall(r"(?<=var SETTINGS = )\S*;", str(request_1_response.content))
            settings = json.loads(result[0][:-1])
            request_1_response_cookies = session.cookies.get_dict()
            x_csrf_token = settings['csrf']
            transId = settings['transId']

            # Random delay
            sleep(randint(10, 20))

            # REQUEST 2 - Login POST
            _LOGGER.info("Logging in to ESB Networks...")
            request_2_response = session.post(
                f'https://login.esbnetworks.ie/esbntwkscustportalprdb2c01.onmicrosoft.com/B2C_1A_signup_signin/SelfAsserted?tx={transId}&p=B2C_1A_signup_signin',
                data={
                    'signInName': self.email,
                    'password': self.password,
                    'request_type': 'RESPONSE'
                },
                headers={
                    'x-csrf-token': x_csrf_token,
                    'User-Agent': self.user_agent,
                    'Accept': 'application/json, text/javascript, */*; q=0.01',
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'X-Requested-With': 'XMLHttpRequest',
                    'Origin': 'https://login.esbnetworks.ie',
                },
                cookies={
                    'x-ms-cpim-csrf': request_1_response_cookies.get('x-ms-cpim-csrf'),
                    'x-ms-cpim-trans': request_1_response_cookies.get('x-ms-cpim-trans'),
                },
                allow_redirects=False
            )

            request_2_response_cookies = session.cookies.get_dict()

            # REQUEST 3 - Confirm login
            request_3_response = session.get(
                'https://login.esbnetworks.ie/esbntwkscustportalprdb2c01.onmicrosoft.com/B2C_1A_signup_signin/api/CombinedSigninAndSignup/confirmed',
                params={
                    'rememberMe': False,
                    'csrf_token': x_csrf_token,
                    'tx': transId,
                    'p': 'B2C_1A_signup_signin',
                },
                headers={'User-Agent': self.user_agent},
                cookies={
                    'x-ms-cpim-csrf': request_2_response_cookies.get('x-ms-cpim-csrf'),
                    'x-ms-cpim-trans': request_2_response_cookies.get('x-ms-cpim-trans'),
                }
            )

            # Check if login was successful
            tester_soup = BeautifulSoup(request_3_response.content, 'html.parser')
            request_3_response_head_test = request_3_response.text[0:21]

            if request_3_response_head_test != "<!DOCTYPE html PUBLIC":
                session.close()
                raise Exception("Login failed - too many retries or session error")

            # Extract authentication tokens
            soup = BeautifulSoup(request_3_response.content, 'html.parser')
            form = soup.find('form', {'id': 'auto'})
            login_url_ = form['action']
            state_ = form.find('input', {'name': 'state'})['value']
            client_info_ = form.find('input', {'name': 'client_info'})['value']
            code_ = form.find('input', {'name': 'code'})['value']

            sleep(randint(2, 5))

            # REQUEST 4 - Complete authentication
            request_4_response = session.post(
                login_url_,
                allow_redirects=False,
                data={'state': state_, 'client_info': client_info_, 'code': code_},
                headers={
                    'User-Agent': self.user_agent,
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Origin': 'https://login.esbnetworks.ie',
                    'Referer': 'https://login.esbnetworks.ie/',
                }
            )

            request_4_response_cookies = session.cookies.get_dict()

            # REQUEST 5 - Access main portal
            request_5_response = session.get(
                'https://myaccount.esbnetworks.ie',
                headers={'User-Agent': self.user_agent},
                cookies={
                    'ARRAffinity': request_4_response_cookies.get('ARRAffinity'),
                    'ARRAffinitySameSite': request_4_response_cookies.get('ARRAffinitySameSite'),
                }
            )

            request_5_response_cookies = session.cookies.get_dict()
            asp_net_core_cookie = request_5_response_cookies.get('.AspNetCore.Cookies')

            sleep(randint(3, 8))

            # REQUEST 6 - Access consumption page
            session.get(
                'https://myaccount.esbnetworks.ie/Api/HistoricConsumption',
                headers={'User-Agent': self.user_agent},
                cookies={
                    'ARRAffinity': request_4_response_cookies.get('ARRAffinity'),
                    'ARRAffinitySameSite': request_4_response_cookies.get('ARRAffinitySameSite'),
                    '.AspNetCore.Cookies': asp_net_core_cookie,
                }
            )

            sleep(randint(2, 5))

            # REQUEST 7 - Get download token
            _LOGGER.info("Getting download token...")
            request_7_response = session.get(
                'https://myaccount.esbnetworks.ie/af/t',
                headers={
                    'User-Agent': self.user_agent,
                    'X-Returnurl': 'https://myaccount.esbnetworks.ie/Api/HistoricConsumption',
                },
                cookies={
                    'ARRAffinity': request_4_response_cookies.get('ARRAffinity'),
                    'ARRAffinitySameSite': request_4_response_cookies.get('ARRAffinitySameSite'),
                }
            )

            file_download_token = json.loads(request_7_response.text)['token']

            # REQUEST 8 - Download data file
            _LOGGER.info("Downloading usage data...")
            request_8_response = session.post(
                'https://myaccount.esbnetworks.ie/DataHub/DownloadHdfPeriodic',
                headers={
                    'User-Agent': self.user_agent,
                    'Content-Type': 'application/json',
                    'X-Xsrf-Token': file_download_token,
                },
                json={
                    'mprn': self.mprn,
                    'searchType': 'intervalkwh'
                }
            )

            session.close()

            # Parse CSV data
            csv_file = request_8_response.content.decode('utf-8')

            if csv_file[0:4] != 'MPRN':
                raise Exception("Invalid CSV format received")

            # Convert to JSON
            my_json = []
            csv_reader = csv.DictReader(csv_file.split('\n'))
            for row in csv_reader:
                if row:  # Skip empty rows
                    my_json.append(row)

            # Process the data for Home Assistant
            total_usage = 0
            readings = []

            for row in my_json:
                try:
                    date_str = row.get('Read Date and End Time', '')
                    usage = float(row.get('Read Value', 0))
                    total_usage += usage

                    readings.append({
                        'date': date_str,
                        'usage': usage,
                        'type': row.get('Read Type', ''),
                    })
                except (ValueError, KeyError) as e:
                    _LOGGER.warning(f"Error parsing row: {e}")
                    continue

            _LOGGER.info(f"Successfully fetched {len(readings)} readings")

            result = {
                'total_usage': total_usage,
                'readings': readings,
                'last_updated': datetime.now().isoformat(),
            }

            # Cache the data for development (only cache serializable data)
            if not DEBUG_USE_CACHE:  # Only cache on real fetches
                try:
                    with open(CACHE_FILE, 'w') as f:
                        json.dump(result, f, indent=2)
                    _LOGGER.info(f"Cached {len(readings)} readings to {CACHE_FILE}")
                except Exception as e:
                    _LOGGER.warning(f"Failed to cache data: {e}")

            return result

        except requests.exceptions.Timeout:
            session.close()
            raise Exception("Request timed out - server not responding")
        except Exception as e:
            session.close()
            _LOGGER.error(f"Error fetching ESB data: {e}")
            raise
