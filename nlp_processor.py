"""
Lambda Function #2: NLP Intent Processor
Processes messages from SQS queue
Extracts intent using pattern matching
Generates responses and stores them in DynamoDB
"""

import json
import boto3
import os
from datetime import datetime
import re

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')

# Environment variables
CONVERSATIONS_TABLE = os.environ.get('CONVERSATIONS_TABLE', 'Conversations')
SESSIONS_TABLE = os.environ.get('SESSIONS_TABLE', 'UserSessions')

# Intent patterns (regex-based NLP)
INTENTS = {
    'greeting': r'\b(hi|hello|hey|greetings|good\s+(morning|afternoon|evening)|howdy|hiya)\b',
    'farewell': r'\b(bye|goodbye|see\s+you|later|farewell|take\s+care)\b',
    'help': r'\b(help|support|assist|assistance|guide|how\s+to)\b',
    'status': r'\b(status|how|what|info|information|update|progress)\b',
    'thanks': r'\b(thanks|thank\s+you|thx|appreciate|grateful)\b',
    'question': r'\b(what|when|where|who|why|how|which|can\s+you)\b',
    'problem': r'\b(issue|problem|error|bug|not\s+working|broken|fail)\b',
    'feedback': r'\b(feedback|comment|suggestion|opinion|think)\b'
}

# Response templates
RESPONSES = {
    'greeting': [
        "Hello! How can I help you today? 👋",
        "Hi there! What can I do for you?",
        "Hey! I'm here to assist you."
    ],
    'farewell': [
        "Goodbye! Have a great day! 👋",
        "See you later! Feel free to come back anytime.",
        "Take care! I'm here if you need anything."
    ],
    'help': [
        "I'm here to help! You can ask me about:\n• Status updates\n• Support and assistance\n• General questions\n• Or just have a chat!",
        "I'd be happy to assist! What do you need help with?",
        "Let me know what you're looking for, and I'll do my best to help!"
    ],
    'status': [
        "Everything is running smoothly! All systems operational. ✅",
        "Status: All good! What specific information would you like?",
        "All systems are functioning normally. What would you like to know more about?"
    ],
    'thanks': [
        "You're welcome! Anything else I can help with? 😊",
        "Happy to help! Let me know if you need anything else.",
        "My pleasure! Feel free to ask if you have more questions."
    ],
    'question': [
        "That's a great question! Let me help you with that.",
        "I'll do my best to answer that for you.",
        "Good question! Here's what I can tell you..."
    ],
    'problem': [
        "I understand you're experiencing an issue. Let me help you troubleshoot.",
        "Sorry to hear you're having trouble. I'm here to help resolve this.",
        "Let me assist you with that problem right away."
    ],
    'feedback': [
        "Thank you for your feedback! We really appreciate it.",
        "I value your input! Your feedback helps us improve.",
        "Thanks for sharing your thoughts!"
    ],
    'default': [
        "I'm processing your message. Could you please provide more details?",
        "Interesting! Tell me more about that.",
        "I'm here to help. Could you rephrase that for me?"
    ]
}

def lambda_handler(event, context):
    """
    Main handler for processing SQS messages
    Extracts intent and generates responses
    """
    try:
        print(f"Processing {len(event['Records'])} messages")
        
        for record in event['Records']:
            message_body = json.loads(record['body'])
            process_message(message_body)
        
        return {
            'statusCode': 200,
            'body': json.dumps({'status': 'processed', 'count': len(event['Records'])})
        }
        
    except Exception as e:
        print(f"Error in NLP processor: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }


def process_message(message_data):
    """
    Main processing logic for each message
    """
    try:
        conversation_id = message_data['conversation_id']
        user_id = message_data['user_id']
        user_message = message_data['message']
        channel = message_data['channel']
        
        print(f"Processing message from {user_id}: {user_message}")
        
        # Detect intent from message
        intent = detect_intent(user_message)
        confidence = calculate_confidence(user_message, intent)
        
        # Generate appropriate response
        bot_response = generate_response(intent, user_message)
        
        # Update user session
        update_session(user_id, intent, channel)
        
        # Store bot response in DynamoDB
        store_bot_response(conversation_id, bot_response, intent, confidence)
        
        # Log analytics
        log_analytics(conversation_id, user_id, intent, confidence, user_message)
        
        print(f"✓ Processed: Intent={intent}, Confidence={confidence}, Response={bot_response[:50]}...")
        
    except Exception as e:
        print(f"Error processing individual message: {str(e)}")
        import traceback
        traceback.print_exc()


def detect_intent(message):
    """
    Use regex patterns to detect user intent
    Returns the first matching intent or 'default'
    """
    message_lower = message.lower().strip()
    
    # Check each intent pattern
    for intent, pattern in INTENTS.items():
        if re.search(pattern, message_lower, re.IGNORECASE):
            return intent
    
    return 'default'


def calculate_confidence(message, intent):
    """
    Calculate confidence score for detected intent
    Simple implementation based on pattern match strength
    """
    if intent == 'default':
        return 0.3
    
    message_lower = message.lower()
    pattern = INTENTS.get(intent, '')
    
    # Count matches
    matches = len(re.findall(pattern, message_lower, re.IGNORECASE))
    
    # More matches = higher confidence
    confidence = min(0.5 + (matches * 0.2), 1.0)
    return round(confidence, 2)


def generate_response(intent, user_message):
    """
    Generate contextual response based on intent
    Uses templates with some variation
    """
    import random
    
    response_list = RESPONSES.get(intent, RESPONSES['default'])
    base_response = random.choice(response_list)
    
    # Add context-aware enhancements
    if intent == 'question' and '?' in user_message:
        base_response += f"\n\nRegarding: '{user_message[:50]}...'"
    
    return base_response


def update_session(user_id, intent, channel):
    """
    Update user session information in DynamoDB
    Tracks user activity and intent history
    """
    try:
        table = dynamodb.Table(SESSIONS_TABLE)
        
        current_time = int(datetime.now().timestamp())
        
        # Try to get existing session
        try:
            response = table.get_item(Key={'user_id': user_id})
            existing_item = response.get('Item', {})
            session_count = existing_item.get('session_count', 0) + 1
            intent_history = existing_item.get('intent_history', [])
        except:
            session_count = 1
            intent_history = []
        
        # Update intent history (keep last 10)
        intent_history.append({
            'intent': intent,
            'timestamp': current_time
        })
        intent_history = intent_history[-10:]
        
        # Update session
        table.put_item(
            Item={
                'user_id': user_id,
                'last_intent': intent,
                'last_activity': current_time,
                'session_count': session_count,
                'channel': channel,
                'intent_history': intent_history
            }
        )
        
        print(f"Updated session for user {user_id}")
        
    except Exception as e:
        print(f"Error updating session: {str(e)}")


def store_bot_response(conversation_id, response, intent, confidence):
    """
    Store bot response in conversations table
    """
    try:
        table = dynamodb.Table(CONVERSATIONS_TABLE)
        timestamp = int(datetime.now().timestamp() * 1000)
        
        table.put_item(
            Item={
                'conversation_id': conversation_id,
                'timestamp': timestamp,
                'message': response,
                'direction': 'outbound',
                'intent': intent,
                'confidence': str(confidence)
            }
        )
        
        print(f"Stored bot response in DynamoDB")
        
    except Exception as e:
        print(f"Error storing bot response: {str(e)}")


def log_analytics(conversation_id, user_id, intent, confidence, message):
    """
    Log analytics data for monitoring and insights
    In production, this could write to a separate analytics table
    """
    analytics_data = {
        'timestamp': datetime.now().isoformat(),
        'conversation_id': conversation_id,
        'user_id': user_id,
        'intent': intent,
        'confidence': confidence,
        'message_length': len(message),
        'message_preview': message[:100]
    }
    
    print(f"Analytics: {json.dumps(analytics_data)}")
