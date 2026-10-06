from app.ai.base import AIProvider
from app.ai.prompt_builder import prompt_builder
from app.config.settings import settings
from app.core.models import AgentPlan, ScreenContext
from app.logging.logger import logger


class OpenAIProvider(AIProvider):
    """
    OpenAI API provider using standard chat completions.
    Integrated with prompt_builder for 9-category intents, Hinglish support,
    targeted semantic patches, and 1-retry self-correction.
    """

    def is_available(self) -> bool:
        return bool(settings.openai_api_key and settings.openai_api_key.strip())

    def plan(self, command: str, context: ScreenContext) -> AgentPlan:
        if not self.is_available():
            from app.ai.local_heuristic import LocalHeuristicPlanner
            return LocalHeuristicPlanner().plan(command, context)

        try:
            from openai import OpenAI
            client = OpenAI(api_key=settings.openai_api_key)

            system_instruction = prompt_builder.build_system_instruction()
            user_prompt = prompt_builder.build_user_prompt(command, context)

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.2
            )

            raw = response.choices[0].message.content or "{}"

            try:
                return prompt_builder.parse_and_validate(raw)
            except ValueError as val_err:
                logger.warning(f"OpenAI output validation failed ({val_err}). Retrying once...")
                retry_prompt = prompt_builder.build_retry_prompt(user_prompt, str(val_err), raw)
                retry_resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": retry_prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1
                )
                retry_raw = retry_resp.choices[0].message.content or "{}"
                return prompt_builder.parse_and_validate(retry_raw)

        except Exception as e:
            logger.warning(f"OpenAI planner error: {e}. Falling back to local heuristic.")
            from app.ai.local_heuristic import LocalHeuristicPlanner
            return LocalHeuristicPlanner().plan(command, context)
