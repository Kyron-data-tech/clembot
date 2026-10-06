from typing import Optional
from app.ai.base import AIProvider
from app.ai.prompt_builder import prompt_builder
from app.config.settings import settings
from app.core.models import AgentPlan, ScreenContext
from app.logging.logger import logger


class GeminiProvider(AIProvider):
    """
    Google Gemini cloud LLM provider using the google-genai SDK.
    Features structured tool calling, dynamic prompt building,
    strict Pydantic schema validation, and automatic 1-retry self-correction.
    """

    def __init__(self):
        self._client = None
        self._client_key: Optional[str] = None

    def _get_client(self):
        """Returns a cached Gemini client with a 30-second planning timeout."""
        from google import genai
        from google.genai import types as gtypes

        key = settings.gemini_api_key
        if self._client is None or self._client_key != key:
            self._client = genai.Client(
                api_key=key,
                http_options=gtypes.HttpOptions(timeout=30_000),  # 30 s planning timeout
            )
            self._client_key = key
        return self._client

    def is_available(self) -> bool:
        return bool(settings.gemini_api_key and settings.gemini_api_key.strip())

    def plan(self, command: str, context: ScreenContext) -> AgentPlan:
        if not self.is_available():
            logger.error("Gemini AI provider is selected but GEMINI_API_KEY is not configured in .env! Falling back to local heuristic.")
            from app.ai.local_heuristic import LocalHeuristicPlanner
            return LocalHeuristicPlanner().plan(command, context)

        try:
            from google import genai
            client = self._get_client()

            system_instruction = prompt_builder.build_system_instruction()
            user_prompt = prompt_builder.build_user_prompt(command, context)

            # Turn 1: Generate plan
            response = client.models.generate_content(
                model=settings.ai_model_name,
                contents=user_prompt,
                config=genai.types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    temperature=0.3
                )
            )

            raw_text = ""
            try:
                raw_text = response.text.strip() if response.text else "{}"
            except Exception:
                if hasattr(response, "candidates") and response.candidates:
                    parts = getattr(response.candidates[0].content, "parts", [])
                    raw_text = "".join(getattr(p, "text", "") for p in parts).strip()
            if not raw_text:
                raw_text = "{}"

            try:
                return prompt_builder.parse_and_validate(raw_text)
            except ValueError as val_err:
                logger.warning(f"Gemini output schema validation failed ({val_err}). Triggering 1-retry self-correction...")

                # Turn 2: Retry with validation feedback
                retry_prompt = prompt_builder.build_retry_prompt(user_prompt, str(val_err), raw_text)
                retry_response = client.models.generate_content(
                    model=settings.ai_model_name,
                    contents=retry_prompt,
                    config=genai.types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        temperature=0.1
                    )
                )
                retry_text = ""
                try:
                    retry_text = retry_response.text.strip() if retry_response.text else "{}"
                except Exception:
                    if hasattr(retry_response, "candidates") and retry_response.candidates:
                        parts = getattr(retry_response.candidates[0].content, "parts", [])
                        retry_text = "".join(getattr(p, "text", "") for p in parts).strip()
                if not retry_text:
                    retry_text = "{}"
                return prompt_builder.parse_and_validate(retry_text)

        except Exception as e:
            logger.error(f"Gemini planner execution error: {e}. Falling back to local heuristic.")
            # Invalidate cached client in case of auth/network error
            self._client = None
            from app.ai.local_heuristic import LocalHeuristicPlanner
            return LocalHeuristicPlanner().plan(command, context)
