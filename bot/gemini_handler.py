import asyncio
import google.generativeai as genai
from google.api_core import exceptions
from typing import List, Dict, Any
import logging

from responses_templates import book_prompts, PROMPT


# Class to handle Gemini API requests
class GeminiHandler:
    def __init__(self, api_keys: List[str]):
        self.api_keys = api_keys
        self.index = 0
        self.configure_model()

    def configure_model(self):
        genai.configure(api_key=self.api_keys[self.index])
        self.model = genai.GenerativeModel("gemini-2.0-flash-thinking-exp-01-21")

    async def generate_response(self, book: str, question: str):
        for _ in range(len(self.api_keys)):  # Iterate through API keys in case of failure
            try:
                response = await asyncio.to_thread(
                    self.model.generate_content, PROMPT.format(book=book, question=question, context="Find in web")
                )
                return response.text
            except exceptions.GoogleAPIError as e:
                logging.warning(f"API key {self.api_keys[self.index]} failed: {e}")
                self.index = (self.index + 1) % len(self.api_keys)
                self.configure_model()

        return "Ошибка при получении ответа. Попробуйте позже."
