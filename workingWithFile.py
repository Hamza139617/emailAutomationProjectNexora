#!/usr/bin/env python3

import yagmail
import os
from google import genai
import csv
import sys
import subprocess
import email
import imaplib
import re
import time
import threading
from flask import Flask, jsonify, send_file
from flask_cors import CORS
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import asyncio
import edge_tts
from playsound import playsound



app = Flask(__name__)
CORS(app)   # allows your HTML file to call this from the browser

# Shared state — the frontend reads this every 3 seconds
system_status = {
    "running":      False,
    "total_phases": 2,
    "team":         [],
    "activity_log": []
}

stop_event = threading.Event()   # set this to pause the automation loop



def log_activity(type_, text, label):
    """Adds an entry to the live activity log AND prints it."""
    system_status["activity_log"].append({
        "type":  type_,
        "text":  text,
        "label": label
    })
    print(f"[{label}] {text}")



def update_team_status():
    """
    Rebuilds the team list in system_status from the
    current global data so the frontend always sees fresh info.
    """
    team = []
    total = len(jobDescriptions[0]) if jobDescriptions else 2
    for i, name in enumerate(names):
        team.append({
            "name":         name,
            "role":         roles[i] if i < len(roles) else "Team Member",
            "phase":        developmentPhase[i] if i < len(developmentPhase) else 0,
            "total_phases": total,
        })
    system_status["team"]         = team
    system_status["total_phases"] = total



async def speak(text):
    filename = f"speech_{int(time.time() * 1000)}.mp3"
    communicate = edge_tts.Communicate(text, voice="en-US-JennyNeural")
    await communicate.save(filename)
    playsound(filename)
    os.remove(filename)


def create_pdf(content: str):
    pdf    = SimpleDocTemplate("Project_Report.pdf")
    styles = getSampleStyleSheet()
    story  = []

    for line in content.split("\n"):
        line = line.strip()
        if not line:
            story.append(Spacer(1, 10))
        elif line.startswith("# "):
            story.append(Paragraph(line[2:], styles["Title"]))
        elif line.startswith("## "):
            story.append(Paragraph(line[3:], styles["Heading1"]))
        elif line.startswith("### "):
            story.append(Paragraph(line[4:], styles["Heading2"]))
        elif line.startswith("- "):
            story.append(Paragraph("* " + line[2:], styles["Normal"]))
        else:
            story.append(Paragraph(line, styles["Normal"]))

    pdf.build(story)


def create_pdf_data(data: str):
    client = genai.Client(api_key="AQ.Ab8RN6KBSHZP6RRpYJIj_wIHwp3QA5kRGxcEMGCT5vz6m1w-pA")

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=(
            "You are an expert report generator. Generate a report about a hotel "
            "construction project using the data below.\n\n"
            "Data:\n" + data + "\n\n"
            "Format: # title  ## headings  ### subheadings  - bullets. "
            "No HTML tags."
        )
    )

    create_pdf(response.text)
    log_activity("pdf", "Project report PDF generated successfully", "PDF")



def extractingInfo(gmails, names, roles, jobDescriptions):
    with open("hotel_project_team.csv", "r") as file:
        data = csv.reader(file)
        next(data)
        for row in data:
            names.append(row[1])
            gmails.append(row[2])
            roles.append(row[3] if len(row) > 3 else "Team Member")  # ← reads role

    check    = False
    tempList = []

    with open("jobDescription.txt", "r") as file:
        reader = file.readlines()
        for i in range(len(reader)):
            for data in reader[i].split('.'):
                if data == 'Job Description 1' or data == 'Job Description 2':
                    check = True
                elif check:
                    tempList.append(data)
                    check = False
                elif data == 'Site':
                    jobDescriptions.append(tempList.copy())
                    tempList.pop()
                    tempList.pop()


def calculatingEmailstoSend(workDone, emailSent, jobDescriptions):
    tempList = []
    for _ in range(len(names)):
        for _ in range(len(jobDescriptions[0])):
            tempList.append(False)
        workDone.append(tempList.copy())
        emailSent.append(tempList.copy())
        for _ in range(len(jobDescriptions[0])):
            tempList.pop()



gmails          = []
names           = []
roles           = []          
jobDescriptions = []
emailSent       = []
workDone        = []
replied_users   = []
developmentPhase = []

data = ""   # project data  for PDF report

# Load everything
extractingInfo(gmails, names, roles, jobDescriptions)
calculatingEmailstoSend(workDone, emailSent, jobDescriptions)


for _ in range(len(names)):
    developmentPhase.append(0)


data += "Names:\n"
for name in names:
    data += name + " "
data += "\nJobs:"
for jobs in jobDescriptions:
    for job in jobs:
        data += job + " "



def run_automation():
    """
    This is the main while loop — now runs in a background thread.
    Checks stop_event so it can be paused via /api/stop.
    """
    log_activity("system", "Automation engine started", "SYSTEM")
    system_status["running"] = True

    while not stop_event.is_set():


        try:
            bot = yagmail.SMTP("hamza139617@gmail.com", os.environ.get("API_KEY"))

            for namesData, gmailData, job, checkEmailSent, phase in zip(
                names, gmails, jobDescriptions, emailSent, developmentPhase
            ):
                if phase < len(jobDescriptions[0]) and checkEmailSent[phase] == False:
                    try:
                        bot.send(
                            to=gmailData,
                            subject="AutomationTest",
                            contents="Respected " + namesData + " \n" + job[phase],
                        )
                        log_activity(
                            "sent",
                            f"Email sent to {namesData} — Phase {phase + 1}",
                            "EMAIL SENT"
                        )
                        update_team_status()   # refresh frontend state
                    except Exception as e:
                        log_activity("error", f"Failed to email {namesData}: {e}", "ERROR")
                    else:
                        checkEmailSent[phase] = True
                    time.sleep(5)

        except Exception as e:
            log_activity("error", f"SMTP error: {e}", "ERROR")


        try:
            EMAIL    = "hamza139617@gmail.com"
            PASSWORD = os.environ.get("API_KEY")

            imap = imaplib.IMAP4_SSL("imap.gmail.com")
            imap.login(EMAIL, PASSWORD)
            imap.select("inbox")

            status, messages = imap.search(None, "UNSEEN")
            email_ids = messages[0].split()

            for e_id in email_ids[-40:]:
                status, msg_data = imap.fetch(e_id, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])

                sender  = msg["From"]
                subject = msg["Subject"]
                date    = msg["Date"]
                body    = ""

                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            try:
                                body = part.get_payload(decode=True).decode()
                            except:
                                body = ""
                else:
                    try:
                        body = msg.get_payload(decode=True).decode()
                    except:
                        body = ""

                for gmail in gmails:
                    if gmail in sender and subject and "AutomationTest" in subject:
                        replied_users.append(gmail)
                        log_activity(
                            "reply",
                            f"Reply from {sender}: {body[:80]}",
                            "REPLY RECEIVED"
                        )

                        string = body[:200]
                        if (string.upper()).count("DONE") >= 1:
                            asyncio.run(speak(sender + " said " + body[:200]))

                            for s in range(len(gmails)):
                                if gmails[s] == gmail:
                                    developmentPhase[s] += 1
                                    if developmentPhase[s] >= len(jobDescriptions[0]):
                                        developmentPhase[s] = len(jobDescriptions[0]) - 1
                                        log_activity(
                                            "pdf",
                                            f"{names[s]} completed all phases — generating report",
                                            "COMPLETE"
                                        )
                                        create_pdf_data(data)
                                    update_team_status()   # refresh frontend
                                    break

            imap.close()
            imap.logout()

        except Exception as e:
            log_activity("error", f"IMAP error: {e}", "ERROR")

        # Wait 30 seconds before next cycle
        stop_event.wait(timeout=30)

    system_status["running"] = False
    log_activity("system", "Automation engine stopped", "SYSTEM")



@app.route('/')
def index():
    """Serves the HTML frontend."""
    return send_file('index.html')


@app.route('/api/status')
def get_status():
    """Frontend polls this every 3 seconds."""
    update_team_status()
    return jsonify(system_status)


@app.route('/api/start', methods=['POST'])
def start_automation():
    """Starts the automation loop in a background thread."""
    global automation_thread
    if not system_status["running"]:
        stop_event.clear()
        automation_thread = threading.Thread(target=run_automation, daemon=True)
        automation_thread.start()
    return jsonify({"status": "started"})


@app.route('/api/stop', methods=['POST'])
def stop_automation():
    """Pauses the automation loop."""
    stop_event.set()
    system_status["running"] = False
    return jsonify({"status": "stopped"})


@app.route('/api/close', methods=['POST'])
def close_system():
    """Closes everything — triggered by Shutdown button in UI."""
    stop_event.set()
    log_activity("system", "System shutdown by user", "SYSTEM")
    os._exit(0)



if __name__ == '__main__':
    print("=" * 50)
    print("  Nexora Project Flow AI — Backend Running")
    print("  Open:  http://localhost:5000")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=False)
