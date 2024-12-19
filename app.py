import os
import time
import json
import threading
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

clock_ins = {}

APP_ID = os.environ.get("APP_ID", "YOUR_APP_ID")
APP_SECRET = os.environ.get("APP_SECRET", "YOUR_APP_SECRET")
HR_USER_ID = os.environ.get("HR_USER_ID", "HR_USER_ID")

BOT_ACCESS_TOKEN = None
TOKEN_EXPIRY = 0

def get_bot_access_token():
    global BOT_ACCESS_TOKEN, TOKEN_EXPIRY
    current_time = int(time.time())
    if BOT_ACCESS_TOKEN is not None and current_time < TOKEN_EXPIRY:
        return BOT_ACCESS_TOKEN

    url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": APP_ID, "app_secret": APP_SECRET})
    data = resp.json()
    print("Token response:", data)
    BOT_ACCESS_TOKEN = data.get("tenant_access_token")
    if BOT_ACCESS_TOKEN:
        TOKEN_EXPIRY = current_time + 7000
    else:
        print("Failed to get tenant_access_token. Check APP_ID/APP_SECRET and permissions.")
    return BOT_ACCESS_TOKEN

def send_message(user_id, text):
    url = "https://open.larksuite.com/open-apis/im/v1/messages?receive_id_type=user_id"
    headers = {
        "Authorization": f"Bearer {get_bot_access_token()}",
        "Content-Type": "application/json"
    }
    safe_text = text.replace("（", "(").replace("）", ")")
    content_str = json.dumps({"text": safe_text})
    payload = {
        "receive_id": user_id,
        "msg_type": "text",
        "content": content_str
    }
    response = requests.post(url, headers=headers, json=payload)
    resp_data = response.json()
    print(f"Sending message to {user_id}: {resp_data}")
    return resp_data

def get_user_info(employee_id):
    """通过employee_id获取用户列表信息，返回items列表"""
    url = "https://open.larksuite.com/open-apis/contact/v3/users"
    headers = {
        "Authorization": f"Bearer {get_bot_access_token()}"
    }
    params = {
        "employee_id": employee_id,
        "employee_id_type": "employee_id",
        "user_id_type": "user_id"
    }
    resp = requests.get(url, headers=headers, params=params)
    data = resp.json()
    print("User list response:", data)
    return data

def get_user_name_by_employee_id(employee_id):
    data = get_user_info(employee_id)
    if data.get("code") == 0:
        items = data.get("data", {}).get("items", [])
        for user in items:
            if user.get("user_id") == employee_id:
                return user.get("name", employee_id)
    return employee_id

def get_user_locale_by_employee_id(employee_id):
    """
    尝试获取用户语言偏好。
    假设返回数据中每个user包含'locale'字段(如'en_US','zh_CN')。
    如果没有locale字段，可以根据是否有en_name来简单判断语言：
    - 若有en_name不为空→英文
    - 否则→中文
    """
    data = get_user_info(employee_id)
    if data.get("code") == 0:
        items = data.get("data", {}).get("items", [])
        for user in items:
            if user.get("user_id") == employee_id:
                # 优先使用locale字段（示例：'en_US','zh_CN'等）
                locale = user.get("locale")
                if locale:
                    if locale.startswith("en"):
                        return "en"
                    else:
                        return "zh"
                # 如果没有locale，则尝试用en_name判断
                en_name = user.get("en_name", "")
                if en_name.strip():
                    return "en"
                else:
                    return "zh"
    # 默认返回中文
    return "zh"

def check_and_notify(employee_id, clock_in_time):
    print(f"Check started for {employee_id}, time: {clock_in_time}")
    # 等待4.5小时 (4.5 * 3600 = 16200 秒)
    time.sleep(10)
    if employee_id in clock_ins:
        # 用户仍未下班
        print(f"User {employee_id} not off-duty after 4.5 hours, reminding user...")
        user_locale = get_user_locale_by_employee_id(employee_id)
        if user_locale == "en":
            # 英文提示
            send_message(employee_id, "You have been working for 4.5 hours. Please take a break and clock out if needed.")
        else:
            # 中文提示
            send_message(employee_id, "您已经连续工作4.5小时，请尽快休息并下班打卡(如果需要)。")

        # 再等待0.5小时 (0.5 * 3600 = 1800秒), 总计5小时
        time.sleep(10)
        if employee_id in clock_ins:
            # 用户仍未下班
            print(f"User {employee_id} not off-duty after 5 hours, reminding HR...")
            user_name = get_user_name_by_employee_id(employee_id)
            # HR 通知不需要语言切换，这里假设一直用中文。如需英文则同样根据HR的locale判断
            # 这里假定HR_USER_ID固定语言，或者统一用中文
            send_message(HR_USER_ID, f"员工 {user_name} 已连续5小时未下班。")
        else:
            print(f"User {employee_id} off-duty within 0.5 hour after employee reminder, no HR reminder needed.")
    else:
        print(f"User {employee_id} off-duty before 4.5 hours, no reminders needed.")

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print("Received event:", data)

    if "challenge" in data:
        return jsonify({"challenge": data["challenge"]})

    header = data.get("header", {})
    event = data.get("event", {})

    create_time_ms = header.get("create_time", 0)
    punch_time = int(create_time_ms) / 1000.0 if create_time_ms else time.time()

    employee_id = event.get("employee_id")
    status_changes = event.get("status_changes", [])

    index_map = {}
    for change in status_changes:
        idx = change.get("index")
        work_type = change.get("work_type")
        current_status = change.get("current_status", "")
        print(f"Found work_type={work_type}, current_status={current_status} for user {employee_id} at index={idx}")
        if idx not in index_map:
            index_map[idx] = []
        index_map[idx].append((work_type, current_status))

    if not index_map:
        print(f"User {employee_id} no index data, no action.")
        return jsonify({"code": 0, "msg": "success"})

    max_index = max(index_map.keys())
    records = index_map[max_index]

    if len(records) == 2:
        first = records[0]  # (on, Normal)
        second = records[1] # (off, '' or Normal)
        if first[0] == "on" and first[1] == "Normal":
            if second[0] == "off":
                if second[1] == "":
                    # 实为上班打卡
                    clock_ins[employee_id] = punch_time
                    print(f"User {employee_id} is actually clock in at index={max_index}, starting check thread.")
                    t = threading.Thread(target=check_and_notify, args=(employee_id, punch_time))
                    t.start()
                elif second[1] == "Normal":
                    # 实为下班打卡
                    if employee_id in clock_ins:
                        del clock_ins[employee_id]
                        print(f"User {employee_id} is actually clock out at index={max_index}, removed from clock_ins.")
                    else:
                        print(f"User {employee_id} is actually clock out at index={max_index}, but not in clock_ins.")
                else:
                    print(f"User {employee_id} at index={max_index}, off status unexpected: {second[1]}")
            else:
                print(f"User {employee_id} at index={max_index}, second record not off: {second}")
        else:
            print(f"User {employee_id} at index={max_index}, first record not (on, Normal): {first}")
    else:
        print(f"User {employee_id} at index={max_index} has unexpected record count: {len(records)}")

    return jsonify({"code": 0, "msg": "success"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("Starting app on port:", port)
    app.run(host="0.0.0.0", port=port)
