#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import configparser
import hmac
import platform
from urllib.parse import urlparse, urlunparse, quote
import requests
import time

MAFREEBOX_API_URL = 'http://mafreebox.freebox.fr/api/v3/'
CONFIG_FILE = '.fbxconfig'
APP_ID = 't411-tracker-update'
APP_VERSION = '0.0.1'
OLD_TRACKER_HOSTS = (
    't411.download:56969',
    'tracker.t411.me:56969',
    'tracker.t411.me:8880',
    'tracker.t411.io:56969',
    'tracker.t411.io:8880',
    '46.246.117.194:56969',
)
NEW_TRACKER_HOST = 't411.download'

def get_api_result(rep):

    if rep.status_code != 200:
        print("http request failed %d / %s" % (rep.status_code, rep.content))
        exit(1)

    try:
        res = rep.json()
    except ValueError as e:
        print("failed to parse response: %s / %s" % (rep.content, e))
        exit(1)
        return

    if 'success' not in res or not res['success']:
        print("failed to parse response")
        exit(1)

    if 'result' in res:
        return res['result']
    return None

def request_token():
    payload = {
        'app_id': APP_ID,
        'app_name': 'T411 tracker updater',
        'app_version': APP_VERSION,
        'device_name': platform.node(),
    }
    rep = requests.post(MAFREEBOX_API_URL + "login/authorize/", json=payload)
    result = get_api_result(rep)
    if 'app_token' not in result or 'track_id' not in result:
        print("Malformed response %s" % rep.content)
        exit(1)

    app_token = result['app_token']
    track_id = result['track_id']

    print("Please press the button on the freebox front panel to grand access to freebox config ...")
    while True:
        time.sleep(2)
        print(" ... checking auth status ...")
        rep = requests.get(MAFREEBOX_API_URL + "login/authorize/%d" % track_id)
        result = get_api_result(rep)
        print("result: %s" % result)

        if 'status' not in result:
            print("unable to get auth status %s" % result)
            exit(1)
        status = result['status']
        if status == 'pending':
            continue

        if status == 'timeout':
            print("... too late. you need to press the button on the freebox front panel !!!")
            exit(1)

        if status == 'granted':
            print("... OK got app_token %s" % app_token)
            return app_token

        print("unexpected status %s" % status)
        exit(1)

def get_freebox_token():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)

    app_token = None

    if 'freebox' in config and 'app_token' in config['freebox']:
        app_token = config['freebox']['app_token']

    if not app_token:
        print("need to request a token")
        app_token = request_token()
        # save in conf
        config['freebox'] = {}
        config['freebox']['app_token'] = app_token

        with open(CONFIG_FILE, 'w') as configfile:
            config.write(configfile)

    return app_token

def get_challenge():
    rep = requests.get(MAFREEBOX_API_URL + "login/")
    res = get_api_result(rep)
    if 'challenge' not in res:
        print("failed to get challenge %s" % res)
        exit(1)
    return res['challenge']

def open_session(app_token):
    challenge = get_challenge()
    password = hmac.new(app_token.encode('utf-8'), msg=challenge.encode('utf-8'), digestmod='sha1').hexdigest()
    rep = requests.post(MAFREEBOX_API_URL + "login/session/", json={
        'password': password,
        'app_id': APP_ID,
        'app_verion': APP_VERSION,
    })
    res = get_api_result(rep)
    if 'session_token' not in res:
        print("failed to get session token %s" % res)
        exit(1)
    return res['session_token']

def get_downloads(session_token):
    rep = requests.get(MAFREEBOX_API_URL + "downloads/", headers={
        'X-Fbx-App-Auth': session_token
    })
    res = get_api_result(rep)
    return res

def get_download_trackers(session_token, download):
    rep = requests.get(MAFREEBOX_API_URL + "downloads/%d/trackers" % download['id'], headers={
        'X-Fbx-App-Auth': session_token
    })
    res = get_api_result(rep)
    return res

def tracker_need_update(announce_url):
    parts = urlparse(announce_url)
    if parts.netloc in OLD_TRACKER_HOSTS:
        return True
    return False

def update_tracker(session_token, download_id, tracker):
    announce_url = tracker['announce']
    parts = list(urlparse(announce_url))
    parts[1] = NEW_TRACKER_HOST
    new_announce = urlunparse(parts)
    print(">  UPDATE tracker %s ==> %s" % (announce_url, new_announce))
    # add new tracker
    url = MAFREEBOX_API_URL + ("downloads/%d/trackers" % download_id)
    rep = requests.post(url, json={
        'announce': new_announce,
        'is_enabled': True
    }, headers={
        'X-Fbx-App-Auth': session_token
    })
    get_api_result(rep)

    # remove prev tracker
    url = MAFREEBOX_API_URL + ("downloads/%d/trackers/%s" % (download_id, quote(announce_url, safe='')))
    rep = requests.delete(url, headers={
        'X-Fbx-App-Auth': session_token
    })
    get_api_result(rep)

    # active new tracker
    url = MAFREEBOX_API_URL + ("downloads/%d/trackers/%s" % (download_id, quote(new_announce, safe='')))
    rep = requests.delete(url, json={
        'is_enabled': True
    }, headers={
        'X-Fbx-App-Auth': session_token
    })
    get_api_result(rep)

def update_trackers():
    print("Getting app token")
    app_token = get_freebox_token()
    print("App token: %s" % app_token)
    print("Opening session ...")
    session_token = open_session(app_token)
    print("got session token: %s" % session_token)
    print("getting download list")
    for d in get_downloads(session_token):
        if 'type' not in d or d['type'] != 'bt':
            print("> skip %s (not a torrent)" % d['name'])
            continue
        print("> processing torrent %s" % d['name'])
        for t in get_download_trackers(session_token, d):
            announce_url = t['announce']
            if tracker_need_update(announce_url):
                update_tracker(session_token, d['id'], t)
            else:
                print(">  KEEP tracker %s" % announce_url)


if __name__ == '__main__':
    update_trackers()

