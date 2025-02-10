import argparse

def parse_args():
    parser = argparse.ArgumentParser(description="Telegram bot settings")
    parser.add_argument('--telegram-token', type=str, required=True, help="Telegram API token")
    parser.add_argument('--gemini-api-keys', nargs='+', required=True, help="List of Gemini API keys")

    parser.add_argument('--gmail-login', type=str, required=False, help="Your Gmail logn")
    parser.add_argument('--gmail-app-password', type=str, required=False, help="Your app_password")
    parser.add_argument('--receivers-email', type=str, required=False, help="Receiver's email")

    args = parser.parse_args()

    if not args.telegram_token or not all(args.gemini_api_keys):
        raise ValueError("Invalid API keys or token provided")

    return args
