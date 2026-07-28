import json
import os
import time

from django.conf import settings

from .feature_flags import require_external_provider_enabled
from .models import AIAuditLog, AIProviderConfig, AIUsageEvent
from .quota import assert_quota_available
from .redaction import redact_mapping


class AIProviderError(RuntimeError):
    pass


class BaseAIProvider:
    provider_name = "base"

    def __init__(self, config=None):
        self.config = config

    def structured_response(self, *, model_config, prompt, input_payload, role, user=None, feature="", request_id=""):
        raise NotImplementedError


class OpenAIProvider(BaseAIProvider):
    provider_name = "openai"

    def structured_response(self, *, model_config, prompt, input_payload, role, user=None, feature="", request_id=""):
        safe_input = redact_mapping(input_payload)
        try:
            require_external_provider_enabled()
        except PermissionError as exc:
            AIUsageEvent.objects.create(
                user=user,
                role=role,
                feature=feature or model_config.feature,
                provider=self.provider_name,
                model_name=model_config.model_name,
                prompt_key=getattr(prompt, "key", ""),
                status=AIUsageEvent.STATUS_SKIPPED,
                request_id=request_id,
                metadata={"reason": "external_provider_disabled"},
            )
            raise AIProviderError(str(exc)) from exc

        assert_quota_available(role, feature or model_config.feature, user=user)
        api_key_env = self.config.api_key_env_var if self.config else "OPENAI_API_KEY"
        api_key = os.environ.get(api_key_env) or getattr(settings, api_key_env, "")
        if not api_key:
            AIUsageEvent.objects.create(
                user=user,
                role=role,
                feature=feature or model_config.feature,
                provider=self.provider_name,
                model_name=model_config.model_name,
                prompt_key=getattr(prompt, "key", ""),
                status=AIUsageEvent.STATUS_SKIPPED,
                request_id=request_id,
                metadata={"reason": "missing_api_key"},
            )
            raise AIProviderError(f"{api_key_env} is not configured.")

        started = time.monotonic()
        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
            response = client.responses.create(
                model=model_config.model_name,
                instructions="\n\n".join(
                    item
                    for item in [
                        prompt.system_prompt,
                        prompt.developer_prompt,
                    ]
                    if item
                ),
                input=json.dumps(
                    safe_input,
                    ensure_ascii=False,
                    default=str,
                ),
                text=(
                    {
                        "format": {
                            "type": "json_schema",
                            "name": prompt.key,
                            "schema": prompt.output_schema,
                        }
                    }
                    if prompt.output_schema
                    else None
                ),
            )
            output_text = getattr(response, "output_text", "") or ""
            usage = getattr(response, "usage", None)
            input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
            output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
            cost = model_config.estimate_cost(input_tokens, output_tokens)
            AIUsageEvent.objects.create(
                user=user,
                role=role,
                feature=feature or model_config.feature,
                provider=self.provider_name,
                model_name=model_config.model_name,
                prompt_key=prompt.key,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost=cost,
                status=AIUsageEvent.STATUS_SUCCESS,
                latency_ms=int((time.monotonic() - started) * 1000),
                request_id=request_id,
            )
            AIAuditLog.objects.create(
                user=user,
                role=role,
                feature=feature or model_config.feature,
                action="provider_request",
                request_id=request_id,
                safe_summary=f"OpenAI response generated for {prompt.key}.",
                metadata={"model": model_config.model_name},
            )
            return output_text
        except Exception as exc:
            AIUsageEvent.objects.create(
                user=user,
                role=role,
                feature=feature or model_config.feature,
                provider=self.provider_name,
                model_name=model_config.model_name,
                prompt_key=getattr(prompt, "key", ""),
                status=AIUsageEvent.STATUS_ERROR,
                latency_ms=int((time.monotonic() - started) * 1000),
                request_id=request_id,
                metadata={"error": exc.__class__.__name__},
            )
            raise AIProviderError(str(exc)) from exc


def provider_for_config(config):
    if config.provider == AIProviderConfig.PROVIDER_OPENAI:
        return OpenAIProvider(config)
    raise AIProviderError(f"Unsupported AI provider: {config.provider}")
