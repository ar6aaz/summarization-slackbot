
from flask import Flask, request, jsonify
import os
import anthropic
import base64
import httpx
import boto3
import json
import requests
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from atlassian import Confluence

app = Flask(__name__)
# Initialize Slack client
slack_token = os.environ['SLACK_BOT_TOKEN']  # Store your Slack Bot Token in environment variable
client = WebClient(token=slack_token)
formatted_messages = []
ACCESS_KEY=os.environ['ACCESS_KEY']
SECRET_KEY=os.environ['SECRET_KEY']
SESSION_TOKEN=os.environ['SESSION_TOKEN']
confluence_url = os.environ['CONFLUENCE_URL']
confluence_user = os.environ['CONFLUENCE_USER']
confluence_password = os.environ['CONFLUENCE_PASSWORD']
space_key = os.environ['CONFLUENCE_SPACE_KEY']

def create_confluence_page(summary, page_title, space_key, confluence_url, confluence_user, confluence_password):
    confluence = Confluence(
        url=confluence_url,
        username=confluence_user,
        password=confluence_password
    )

    parent_page_id = None  # Set this to the ID of the parent page if needed
    body = summary

    new_page = confluence.create_page(
        space=space_key,
        title=page_title,
        body=body,
        parent_id=parent_page_id
    )

    print(f"New page created: {new_page['_links']['tinyui']}")
    return new_page['_links']['tinyui']

@app.route('/slack/events', methods=['POST'])
def handle_slack_events():

    request_data = request.get_json()
    if 'challenge' in request_data:
        challenge = request_data['challenge']
        return jsonify({'challenge': challenge}), 200
    
    # Verify the request is from Slack
    if not verify_slack_request(request):
        return jsonify({'error': 'Invalid request'}), 400

    # Parse the incoming event data
    event_data = request.get_json()
    print("   #######   event data is \n ",event_data)

    # Check if the event is an app_mention event
    if event_data.get('event', {}).get('type') == 'app_mention':
        channel_id = event_data['event']['channel']
        thread_ts = event_data['event'].get('thread_ts') or event_data['event']['ts']

        print ("channel id is *******: ",channel_id)
        print ("thread ts is********: ",thread_ts)

        # Make a POST request to your /summarize route
        ngrok_url = os.environ['NGROK_URL']  # Replace with your actual Ngrok URL
        response = requests.post(f'{ngrok_url}/summarize', json={
            'channel_id': channel_id,
            'thread_ts': thread_ts
        })

        if response.status_code == 200:
            summary = response.json()['summary']
            # Post the summary back to the Slack channel (optional)
            post_message_to_slack(channel_id, summary, thread_ts)
        else:
            print(f'Error: {response.text}')

    return jsonify({'status': 'ok'})

# Helper functions
def verify_slack_request(request):
    # Implement your request verification logic here
    return True

def post_message_to_slack(channel_id, message, thread_ts):
    try:
        response = client.chat_postMessage(
            channel=channel_id,
            text=message,
            thread_ts=thread_ts
        )
        print(f"Message posted successfully: {response['ts']}")
    except SlackApiError as e:
        if e.response['error'] == 'missing_scope':
            missing_scope = e.response['needed']
            print(f"Missing scope: {missing_scope}. Please add the required scope to your Slack App. Message is {message}")
        else:
            print(f"Error posting message: {e.response['error']}")



def get_slack_thread_messages(channel_id, thread_ts):
    try:
        response = client.conversations_replies(channel=channel_id, ts=thread_ts)
        messages = response['messages']
        return messages
    except SlackApiError as e:
        print(f"Error fetching thread: {e.response['error']}")
        return None

def format_messages_for_model(messages):
    # print(messages)
    for message in messages:
        user = message.get('user', 'unknown')
        text = message.get('text', '')
        files = message.get('files', [])

        if text:
            formatted_messages.append(f"{user}: {text}")

        for file in files:
            if file['mimetype'].startswith('image/'):
                image_url = file['url_private']
                formatted_messages.append(f"{user}: [Image] {image_url}")

    return "\n".join(formatted_messages)


def summarize_thread(channel_id, thread_ts):
    # Fetch the thread messages
    messages = get_slack_thread_messages(channel_id, thread_ts)
    if not messages:
        return "No messages found or error fetching messages."

    thread_text = format_messages_for_model(messages)
    # prompt = f"Extract insights from the following Slack conversation, focused on engineering challenges including code issues and infrastructure setup. For the posted problem, find out the solution from the thread conversation.Be concise.Provide a straightforward answer. Your task is to provide a clear summary.Do not make it narrative, do not mention users. Just provide what was the question and what is the final solution.Here is the discussion text:\n\n{thread_text}\n\n:"
    prompt = f"Extract insights from the following Slack conversation, focused on engineering challenges including code issues and infrastructure setup. Identify the initial problem and find out what was the solution from the thread conversation.Be concise.Provide a straightforward answer. Your task is to provide a clear summary.Do not make it narrative, do not mention it like 'The user did this' or 'The user did that'. Instead, just provide what was the question and what is the final solution in an instructional manner. Here is the discussion text:\n\n{thread_text}\n\n:"

    # Bedrock Runtime
    # bedrock_runtime = boto3.client(service_name="bedrock-runtime", region_name="us-east-1")
    bedrock_runtime = boto3.client(
    service_name="bedrock-runtime",
    region_name="us-east-1",
    aws_access_key_id=ACCESS_KEY,      # optional - set this value if you haven't run `aws configure` 
    aws_secret_access_key=SECRET_KEY,  # optional - set this value if you haven't run `aws configure`
    aws_session_token=SESSION_TOKEN,   # optional - set this value if you haven't run `aws configure`
)

    # Model configuration
    model_id = "anthropic.claude-3-haiku-20240307-v1:0"
    model_kwargs = {
        "max_tokens": 2048,
        "temperature": 0.1,
        "top_k": 250,
        "top_p": 1,
        "stop_sequences": ["\n\nHuman"],
    }

    # Input configuration
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "system": "You are an honest and helpful bot.",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt}
                ]
            }
        ],
    }

    # Add image URLs to the body
    for message in formatted_messages:
        if '[Image]' in message:
            image_file_id = message.split('[Image]')[1].strip()
            print(f"Fetching image with file ID: {image_file_id}")
            try:
                print("hellloooooooooo")
                file_info = client.files_info(file=image_file_id)
                print("this is file info")
                public_url = client.files_sharedPublicURL(file=image_file_id)
                print("Public URL: {public_url}")
                image_data = httpx.get(public_url['file']['permalink_public']).content
                image_data = base64.b64encode(image_data).decode('utf-8')
                image_media_type = file_info['file']['mimetype']
                body['messages'][0]['content'].append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image_media_type,
                        "data": image_data,
                    }
                })
            except SlackApiError as e:
                print(f"Error fetching image: {e.response['error']}")

    body.update(model_kwargs)

    # Invoke
    response = bedrock_runtime.invoke_model(modelId=model_id, body=json.dumps(body))

    # Process and print the response
    result = json.loads(response.get("body").read()).get("content", [])[0].get("text", "")
    return result

# Example usage
# channel_id = 'C0755GWLGAD'  # Replace with your channel ID
# thread_ts = '1716459769.164459'  # Replace with the timestamp of the thread's parent message, this is image wala
# thread_ts = '1716459443.426039' # this is boto3t
# summary = summarize_thread(channel_id, thread_ts)
# print("Summary:", summary)

@app.route('/summarize', methods=['POST'])
def summarize():
    data = request.json
    channel_id = data.get('channel_id')
    thread_ts = data.get('thread_ts')
    print('data: ', data)

    if not channel_id or not thread_ts:
        return jsonify({'error': 'Missing channel_id or thread_ts'}), 400

    summary = summarize_thread(channel_id, thread_ts)
    page_title = f"Summary for Thread {thread_ts}"
    print("page_title: ", page_title)

    page_url = create_confluence_page(summary, page_title, space_key, confluence_url, confluence_user, confluence_password)
    print(f"Confluence page URL: {page_url}")
    confluence_message = summary + 'Here is the confluence runbook created for the issue: ' + page_url
    return jsonify({'confluence_message': confluence_message})

if __name__ == '__main__':
    app.run(host='0.0.0.0',port=5000)
