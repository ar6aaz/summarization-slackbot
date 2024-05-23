
from flask import Flask, request, jsonify
import os
import anthropic
import base64
import httpx
import boto3
import json
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

app = Flask(__name__)
# Initialize Slack client
slack_token = os.environ['SLACK_BOT_TOKEN']  # Store your Slack Bot Token in environment variable
client = WebClient(token=slack_token)
formatted_messages = []

def get_slack_thread_messages(channel_id, thread_ts):
    try:
        response = client.conversations_replies(channel=channel_id, ts=thread_ts)
        messages = response['messages']
        return messages
    except SlackApiError as e:
        print(f"Error fetching thread: {e.response['error']}")
        return None

def format_messages_for_model(messages):
    print(messages)
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
    prompt = f"Summarize the following thread, including any text from images:\n\n{thread_text}\n\nSummary:"

    # Bedrock Runtime
    bedrock_runtime = boto3.client(service_name="bedrock-runtime", region_name="us-east-1")

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
channel_id = 'C0755GWLGAD'  # Replace with your channel ID
# thread_ts = '1716459769.164459'  # Replace with the timestamp of the thread's parent message
thread_ts = '1716459443.426039'
summary = summarize_thread(channel_id, thread_ts)
print("Summary:", summary)

@app.route('/summarize', methods=['POST'])
def summarize():
    data = request.json
    channel_id = data.get('channel_id')
    thread_ts = data.get('thread_ts')

    if not channel_id or not thread_ts:
        return jsonify({'error': 'Missing channel_id or thread_ts'}), 400

    summary = summarize_thread(channel_id, thread_ts)
    return jsonify({'summary': summary})

if __name__ == '__main__':
    app.run(port=5000)