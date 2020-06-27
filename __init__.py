from mycroft import MycroftSkill, intent_file_handler, intent_handler
from mycroft.skills.core import resting_screen_handler
from time import sleep
from os.path import join, dirname
import tempfile
import requests
from datetime import timedelta, datetime
from lingua_franca.format import nice_date
from lingua_franca.parse import extract_datetime
import random
from adapt.intent import IntentBuilder

# HACK
# workaround raise SSLError(e, request=request) requests.exceptions.SSLError: HTTPSConnectionPool(host='gibs.earthdata.nasa.gov', port=443): Max retries exceeded with url: /wmts/epsg4326/best/wmts.cgi?SERVICE=WMTS&request=GetCapabilities (Caused by SSLError(SSLError(1, '[SSL: WRONG_SIGNATURE_TYPE] wrong signature type (_ssl.c:1108)'))
# see https://github.com/psf/requests/issues/4775
from requests import adapters
import ssl
from urllib3 import poolmanager
import geocoder


class TLSAdapter(adapters.HTTPAdapter):

    def init_poolmanager(self, connections, maxsize, block=False):
        """Create and initialize the urllib3 PoolManager."""
        ctx = ssl.create_default_context()
        ctx.set_ciphers('DEFAULT@SECLEVEL=1')
        self.poolmanager = poolmanager.PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_version=ssl.PROTOCOL_TLS,
            ssl_context=ctx)


class VIIRSSkill(MycroftSkill):
    def __init__(self):
        super(VIIRSSkill, self).__init__(name="VIIRS MyHouseFromSpace Skill")
        if "res" not in self.settings:
            self.settings["res"] = "250m"
        if "zoom" not in self.settings:
            self.settings["zoom"] = 8
        if "random" not in self.settings:
            # idle screen, random or latest
            self.settings["random"] = True
        # HAck around requests bug
        self.session = requests.session()
        self.session.mount('https://', TLSAdapter())

    def initialize(self):
        # state tracking
        self.current_zoom = self.settings["zoom"]
        self.current_date = None
        self.current_location = self.location_pretty
        self.geocache = {
            self.location_pretty: (self.location["coordinate"]["latitude"],
                                   self.location["coordinate"]["longitude"])
        }

    def validate_date(self, date):

        url = "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/1.0.0/WMTSCapabilities.xml"
        latest_date = self.session.get(url).text.split(
            "<ows:Identifier>MODIS_Terra_CorrectedReflectance_TrueColor</ows"
            ":Identifier>")[1].split("</Layer>")[0].split(
            "<ows:Identifier>Time</ows:Identifier>")[1].split("<Value>")[
            1].split(
            "</Value>")[0].split("/")[1]

        # HACK this date is not correct
        # we can not check per location, bugs out around midnight
        h = datetime.now().hour
        if h < 12:
            tmp = datetime.strptime(latest_date, "%Y-%m-%d")
            tmp -= timedelta(days=1)
            latest_date = tmp.strftime("%Y-%m-%d")
        # /end hack

        if not date:
            return latest_date
        if not isinstance(date, str):
            date = date.strftime("%Y-%m-%d")
        y, m, d = date.split("-")
        y2, m2, d2 = latest_date.split("-")
        if y > y2:
            date = latest_date
        elif m > m2 and y == y2:
            date = latest_date
        elif d > d2 and m == m2 and y == y2:
            date = latest_date
        return date

    def geolocate(self, address, try_all=True):
        if address in self.geocache:
            return self.geocache[address]
        try:
            # should be installed from default skills
            from astral.geocoder import database, lookup
            # see https://astral.readthedocs.io/en/latest/#cities
            a = lookup(address, database())
            self.geocache[address] = (a.latitude, a.longitude)
            return a.latitude, a.longitude
        except:
            pass  # use online geocoder

        location_data = geocoder.osm(address)
        if not location_data.ok:
            location_data = geocoder.geocodefarm(address)
        if try_all:
            # more are just making it slow
            if not location_data.ok:
                location_data = geocoder.google(address)
            if not location_data.ok:
                location_data = geocoder.arcgis(address)
            if not location_data.ok:
                location_data = geocoder.bing(address)
            if not location_data.ok:
                location_data = geocoder.canadapost(address)
            if not location_data.ok:
                location_data = geocoder.yandex(address)
            if not location_data.ok:
                location_data = geocoder.tgos(address)

        if location_data.ok:
            location_data = location_data.json
            lat = location_data.get("lat")
            lon = location_data.get("lng")
            self.geocache[address] = (lat, lon)
            return lat, lon
        raise ValueError

    def get_picture(self, lat, lon, date=None, zoom=None, sat=None):
        gibs = "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/MODIS_{sat}_CorrectedReflectance_TrueColor/default/{date}/{res}/{zoom}/{row}/{col}.jpg"
        date = date or datetime.now()
        if not isinstance(date, str):
            date = date.strftime("%Y-%m-%d")

        level = zoom or self.settings["zoom"]
        if level < 0:
            level = 0
        if level > 8:
            level = 8

        row = ((90 - lat) * (2 ** level)) // 288
        col = ((180 + lon) * (2 ** level)) // 288

        url = gibs.format(date=date, zoom=int(level),
                          row=int(row), col=int(col),
                          res=self.settings["res"], sat=sat)
        path = join(tempfile.gettempdir(),
                    "viiirs_{row}_{col}_{zoom}_{res}_{date}.jpg".
                    format(date=date, zoom=int(level),
                           row=int(row), col=int(col),
                           res=self.settings["res"]))
        r = self.session.get(url)
        with open(path, "wb") as f:
            f.write(r.content)
        return path

    def update_picture(self, zoom=None, sat=None, date=None, lat=None,
                       lon=None):
        lat = lat or self.location["coordinate"]["latitude"]
        lon = lon or self.location["coordinate"]["longitude"]
        date = self.validate_date(date)
        sat = sat or random.choice(["Terra", "Aqua"])

        self.gui['imgLink'] = self.settings['imgLink'] = \
            self.get_picture(lat, lon, date, zoom, sat)
        self.gui['date_str'] = date
        self.gui["sat"] = "MODIS " + sat
        self.gui['lat'] = lat
        self.gui['lon'] = lon
        try:
            location = self.gui["location"]
        except:
            location = self.location_pretty
        self.gui["title"] = "{location} {date}" \
            .format(date=date, location=location)
        self.gui["caption"] = "Latitude: {lat}  Longitude: {lon}" \
            .format(lat=lat, lon=lon)
        self.set_context("VIIRS")
        # save date for follow up intents
        self.current_date = datetime.strptime(date, "%Y-%m-%d")
        self.current_location = location
        self.current_zoom = zoom

    @resting_screen_handler("VIIRS")
    def idle(self, message):
        self.gui.clear()
        date = datetime.now()
        if self.settings["random"]:
            year = random.randint(2004, date.year)
            if year == date.year:
                month = random.randint(1, date.month)
                day = random.randint(1, date.day)
            else:
                month = random.randint(1, 12)
                day = random.randint(1, 28)
            date = "{y}-{m}-{d}".format(y=year, m=month, d=day)
        self.update_picture(date=date)
        self.gui.show_page('idle.qml')

    # intents
    @intent_file_handler("about.intent")
    def handle_about(self, message):
        viirs = join(dirname(__file__), "ui", "images", "viirs.png")
        utterance = self.dialog_renderer.render("aboutVIIRS", {})
        self.gui.show_image(viirs, override_idle=True,
                            fill='PreserveAspectFit',
                            caption=utterance)
        self.speak(utterance, wait=True)
        sleep(1)
        self.gui.clear()

    def _display_and_speak(self, date, location):
        lat, lon = None, None
        self.gui["location"] = self.location_pretty
        if location:
            try:
                lat, lon = self.geolocate(location)
            except:
                self.speak_dialog("location.error", {"location": location})
                return
            self.gui["location"] = location
        self.update_picture(date=date, lat=lat, lon=lon)
        if date:
            # TODO validate date and speak error message if in future
            # will still display most recent, but want to signal user
            if isinstance(date, str):
                date = datetime.strptime(date, "%Y-%m-%d")
            delta = date - self.current_date
            if delta:
                self.speak_dialog("bad.date")

        self.gui.show_image(self.gui['imgLink'],
                            title=self.gui['title'],
                            caption=self.gui["caption"],
                            fill='PreserveAspectFit')
        date = nice_date(self.current_date, lang=self.lang)
        if location:
            self.speak_dialog("location",
                              {"date": date, "location": location}, wait=True)
        else:
            self.speak_dialog("house", {"date": date}, wait=True)

    @intent_file_handler('viirs.intent')
    @intent_file_handler('viirs_time.intent')
    @intent_file_handler('viirs_location.intent')
    def handle_viirs(self, message):
        date = extract_datetime(message.data["utterance"], lang=self.lang)
        if date:
            date = date[0]
        location = message.data.get("location")
        self._display_and_speak(date, location)

    @intent_handler(IntentBuilder("WhyCloudsIntent")
                    .require("why").require("clouds").require("VIIRS"))
    def handle_clouds(self, message):
        self.speak_dialog("clouds", wait=True)

    @intent_handler(IntentBuilder("PrevSatPictureIntent")
                    .require("previous").require("picture").require("VIIRS"))
    def handle_prev(self, message):
        date = self.current_date - timedelta(days=1)
        location = self.current_location
        self._display_and_speak(date, location)

    @intent_handler(IntentBuilder("NextSatPictureIntent")
                    .require("next").require("picture").require("VIIRS"))
    def handle_next(self, message):
        date = self.current_date + timedelta(days=1)
        location = self.current_location
        self._display_and_speak(date, location)

    def handle_set_zoom(self, message):
        raise NotImplementedError

    def handle_zoom_out(self, message):
        raise NotImplementedError

    def handle_zoom_in(self, message):
        raise NotImplementedError


def create_skill():
    return VIIRSSkill()
