#import sqlite3

from flask import Flask

app = Flask(__name__)

@app.route("/")
def test():
    return "<p>testing, works</p>"

def admin():
    return "admin bro"

def user():
    return "user bro"
