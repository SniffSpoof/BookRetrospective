import argparse

def parse_args():
    parser = argparse.ArgumentParser(description="Telegram bot settings")
    parser.add_argument('--telegram-token', type=str, required=True, help="Telegram API token")
    parser.add_argument('--gemini-api-keys', nargs='+', required=True, help="List of Gemini API keys")
    args = parser.parse_args()

    if not args.telegram_token or not all(args.gemini_api_keys):
        raise ValueError("Invalid API keys or token provided")

    return args
