from mycroft import MycroftSkill, intent_file_handler, intent_handler
from mycroft.skills.core import resting_screen_handler
from adapt.intent import IntentBuilder
from time import sleep
from os.path import join, dirname
from datetime import datetime
import tempfile
import requests


class VIIRSSkill(MycroftSkill):
    def __init__(self):
        super(VIIRSSkill, self).__init__(name="VIIRS MyHouseFromSpace Skill")
        if "res" not in self.settings:
            self.settings["res"] = "250m"
        if "zoom" not in self.settings:
            self.settings["zoom"] = 5

    def get_picture(self, lat, lon, date=None, zoom=None):
        gibs = "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/MODIS_Terra_CorrectedReflectance_TrueColor/default/{date}/{res}/{zoom}/{row}/{col}.jpg"
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

        url = gibs.format(date=date, zoom=level, row=int(row), col=int(col),
                           res=self.settings["res"])
        path = join(tempfile.gettempdir(), "viiirs.jpg")
        r = requests.get(url)
        with open(path, "wb") as f:
            f.write(r.content)
        return path

    def update_picture(self, zoom=5):
        lat = self.location["coordinate"]["latitude"]
        lon = self.location["coordinate"]["longitude"]
        date = datetime.now().strftime("%Y-%m-%d")
        self.gui['imgLink'] = self.get_picture(lat, lon, date, zoom)
        self.gui['date'] = date
        self.gui['lat'] = lat
        self.gui['lon'] = lon
        self.gui["title"] = "Latitude: {lat}  Longitude: {lon}".format(
            lat=lat, lon=lon)
        self.set_context("VIIRS")

    @resting_screen_handler("VIIRS")
    def idle(self, message):
        self.update_picture()
        self.gui.clear()
        self.gui.show_page('idle.qml')

    # intents
    @intent_file_handler("about.intent")
    def handle_about(self, message):
        epic = join(dirname(__file__), "ui", "images", "viirs.png")
        utterance = self.dialog_renderer.render("aboutVIIRS", {})
        self.gui.show_image(epic, override_idle=True,
                            fill='PreserveAspectFit', caption=utterance)
        self.speak(utterance, wait=True)
        sleep(1)
        self.gui.clear()

    @intent_file_handler('viirs.intent')
    def handle_viirs(self, message):
        self.gui.clear()
        self.update_picture()
        self.gui.show_image(self.gui['imgLink'],
                            title=self.gui['title'],
                            fill='PreserveAspectFit')

        self.speak_dialog("house", wait=True)
        sleep(1)
        self.gui.clear()


def create_skill():
    return VIIRSSkill()
