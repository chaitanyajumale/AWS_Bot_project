"""
Lambda Function #1: Message Router (Function URL Version)
Routes incoming messages from multiple channels to SQS queue
Works with Lambda Function URLs (no API Gateway needed - Always Free!)
"""

import json
import boto3
import os
from datetime import datetime
import hashlib

# Initialize AWS clients
sqs = boto3.client('sqs')
dynamodb = boto3.resource('dynamodb')

# Environment variables
QUEUE_URL = os.environ.get('SQS_QUEUE_URL', '')
CONVERSATIONS_TABLE = os.environ.get('CONVERSATIONS_TABLE', 'Conversations')

def lambda_handler(event, context):
    """
    Main handler for routing messages
    Accepts messages from Lambda Function URL and routes to SQS
    """
    try:
        print(f"Received event: {json.dumps(event)}")
        
        # Parse request body
        if 'body' in event:
            body = json.loads(event['body']) if isinstance(event['body'], str) else event['body']
        else:
            body = event
        
        # Extract channel from body (Function URL doesn't have path parameters)
        channel = body.get('channel', 'web')
        
        # Extract message and user info based on channel
        message = extract_message(body, channel)
        user_id = extract_user_id(body, channel)
        
        if not message:
            return response(400, {'error': 'No message provided'})
        
        # Generate unique conversation ID
        conversation_id = generate_conversation_id(user_id, channel)
        
        # Store incoming message in DynamoDB
        store_message(conversation_id, user_id, message, channel, 'inbound')
        
        # Prepare message for SQS
        queue_message = {
            'conversation_id': conversation_id,
            'user_id': user_id,
            'message': message,
            'channel': channel,
            'timestamp': int(datetime.now().timestamp())
        }
        
        # Send to SQS for async processing
        sqs_response = sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(queue_message)
        )
        
        print(f"Message sent to SQS: {sqs_response['MessageId']}")
        
        return response(200, {
            'status': 'queued',
            'message_id': sqs_response['MessageId'],
            'conversation_id': conversation_id,
            'channel': channel
        })
        
    except Exception as e:
        print(f"Error in message router: {str(e)}")
        import traceback
        traceback.print_exc()
        return response(500, {'error': str(e)})


def extract_message(body, channel):
    """Extract message content based on channel format"""
    if channel == 'slack':
        event = body.get('event', {})
        return event.get('text', body.get('message', ''))
    elif channel == 'telegram':
        message_obj = body.get('message', {})
        return message_obj.get('text', body.get('message', ''))
    else:  # web or generic
        return body.get('message', '')


def extract_user_id(body, channel):
    """Extract user ID based on channel format"""
    if channel == 'slack':
        event = body.get('event', {})
        return event.get('user', body.get('user_id', 'unknown'))
    elif channel == 'telegram':
        message_obj = body.get('message', {})
        from_obj = message_obj.get('from', {})
        return str(from_obj.get('id', body.get('user_id', 'unknown')))
    else:  # web
        return body.get('user_id', body.get('userId', 'web_user'))


def generate_conversation_id(user_id, channel):
    """Generate unique conversation ID per user per channel per day"""
    date_str = datetime.now().strftime('%Y%m%d')
    key = f"{user_id}_{channel}_{date_str}"
    return hashlib.md5(key.encode()).hexdigest()


def store_message(conversation_id, user_id, message, channel, direction):
    """Store message in DynamoDB conversations table"""
    try:
        table = dynamodb.Table(CONVERSATIONS_TABLE)
        timestamp = int(datetime.now().timestamp() * 1000)
        
        item = {
            'conversation_id': conversation_id,
            'timestamp': timestamp,
            'user_id': user_id,
            'message': message,
            'channel': channel,
            'direction': direction
        }
        
        table.put_item(Item=item)
        print(f"Stored message in DynamoDB: {conversation_id}")
        
    except Exception as e:
        print(f"Error storing message: {str(e)}")
        pass


def response(status_code, body):
    """Generate Lambda Function URL response"""
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Allow-Methods': 'OPTIONS,POST,GET'
        },
        'body': json.dumps(body)
    }
