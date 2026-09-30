import asyncio
import openai
from openai import AsyncOpenAI
import pandas as pd
from typing import List, Optional
from core.prompt_engine import PromptGenerator
import backoff
import streamlit as st
import tiktoken
import time


class AsyncModelInference:
    """
    Asynchronous model inference class.

    Args:
        prompts_path (str): The path to the prompts file.
        dataset (List[str]): The dataset to use for inference.
        token (str): The token to use for inference.
        prompt_type (str): The type of prompt to use.
        data_type (str): Takes arguments 'abstracts' or 'fulltext' for the type of data to use.
        model (str): The model to use for inference.

    Attributes:
        dataset (List[str]): The dataset to use for inference.
        prompt (PromptGenerator): The prompt generator.
        client (AsyncOpenAI): The OpenAI client.
        data_type (str): The type of data to use.
        model (str): The model to use for inference.
        semaphore (asyncio.Semaphore): The semaphore to use for rate limiting.

    Methods:
        estimate_tokens(prompt: str) -> int: Estimates the number of tokens in a prompt.
        _query(prompt: str, kind: str = "abstracts") -> Optional[dict]: Queries the model.
        _batch_inference_with_token_limit(prompts: List[str], kind: str) -> List[Optional[dict]]: Batch inference with token limit.
        llm_inference(objectives: List[str], criteria: str, token_estimate: bool) -> List[Optional[dict]]: LLM inference.
        run_inference(objectives: List[str], criteria: str, token_estimate: bool) -> List[Optional[dict]]: Run inference.
        response_to_dataframe(responses: List[Optional[dict]]) -> pd.DataFrame: Converts responses to a dataframe.

    Example:
        >>> model_query = AsyncModelInference(
        >>>     prompts_path="prompts.json",
        >>>     dataset=["abstract1", "abstract2", "abstract3"],
        >>>     token="your-token",
        >>>     prompt_type="baseline_abstract",
        >>>     data_type="abstracts",
        >>>     model="gpt-4o-mini",
        >>>     max_concurrent_requests=10,
        >>>     rpm_limit=100,
        >>>     batch_size=10,
        >>>     batch_delay=0.1
        >>> )
        >>> responses = model_query.run_inference(
        >>>     objectives=["objective1", "objective2"],
        >>>     criteria="prompt with criteria",
        >>>     token_estimate=True
        >>> )
        >>> print(responses)
    """

    # --- Constants ---
    MODEL = st.secrets["model_params"]["model"]
    MAX_CONCURRENT_REQUESTS = st.secrets["model_params"]["max_concurrent_requests"]
    RPM_LIMIT = st.secrets["model_params"]["rpm_limit"]
    BATCH_SIZE = st.secrets["model_params"]["batch_size"]
    BATCH_DELAY = st.secrets["model_params"]["batch_delay"]
    TEMPERATURE = st.secrets["model_params"]["temperature"]
    TOP_P = st.secrets["model_params"]["top_p"]
    FREQUENCY_PENALTY = st.secrets["model_params"]["frequency_penalty"]
    PRESENCE_PENALTY = st.secrets["model_params"]["presence_penalty"]
    MAX_TPM = st.secrets["model_params"]["max_tpm"]

    def __init__(
        self,
        prompts_path: str,
        dataset: List[str],
        token: str,
        prompt_type: str,
        data_type: str,
        model: str = MODEL,
        max_concurrent_requests: int = MAX_CONCURRENT_REQUESTS,
        rpm_limit: int = RPM_LIMIT,
        batch_size: int = BATCH_SIZE,
        batch_delay: float = BATCH_DELAY
    ):
        self.dataset = dataset
        self.prompt = PromptGenerator(prompts_path, prompt_type)
        self.client = AsyncOpenAI(api_key=token)
        self.data_type = data_type
        self.model = model
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)
        self.delay = 60 / rpm_limit  # delay between requests
        self.batch_size = batch_size
        self.batch_delay = batch_delay

    @staticmethod
    def estimate_tokens(prompt: str) -> int:
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(prompt))

    @backoff.on_exception(backoff.expo, openai.APIError, max_tries=5)
    async def _query(self, prompt: str) -> Optional[dict]:
        async with self.semaphore:
            await asyncio.sleep(self.delay)
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                f"You are an expert in systematic and scoping reviews. "
                                f"Evaluate the provided {self.data_type} against predefined inclusion and exclusion criteria. "
                                f"Decision policy: INCLUDE only if all inclusion criteria are met; EXCLUDE if any exclusion criterion applies. "
                                f"Evidence use: quote short phrases when possible; do not invent details. "
                                f"Uncertainty: if information is insufficient or ambiguous, prefer 'YYY'. "
                                f"Output contract: provide a very brief rationale (≤2 sentences), then on the final line ONLY output 'XXX' or 'YYY' with no extra text."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=self.TEMPERATURE,
                    top_p=self.TOP_P,
                    frequency_penalty=self.FREQUENCY_PENALTY,
                    presence_penalty=self.PRESENCE_PENALTY,
                )
                return response.model_dump() 
            except Exception as e:
                print(f"Error processing prompt: {e}")
                return None

    async def _batch_inference_with_token_limit(self, prompts: List[str]) -> List[Optional[dict]]:
        max_tpm = self.MAX_TPM
        window_start = time.time()
        used_tokens = 0
        responses = []

        for i, prompt in enumerate(prompts):
            prompt_tokens = self.estimate_tokens(prompt)

            # Reset window if 60s passed
            now = time.time()
            if now - window_start >= 60:
                window_start = now
                used_tokens = 0

            # Wait if this request would go over limit
            while used_tokens + prompt_tokens > max_tpm:
                sleep_time = max(0.5, 60 - (time.time() - window_start))
                await asyncio.sleep(sleep_time)
                now = time.time()
                if now - window_start >= 60:
                    window_start = now
                    used_tokens = 0

            # Run the request
            response = await self._query(prompt)
            responses.append(response)
            used_tokens += prompt_tokens
            await asyncio.sleep(self.delay)  # still respect RPM delay

        return responses

    async def llm_inference(self, objectives: List[str], criteria: str) -> List[Optional[dict]]:
        prompts = [
            self.prompt.abstract_prompt(abstract=data, objectives=objectives, criteria=criteria)
            if self.data_type == "abstracts"
            else self.prompt.fulltext_prompt(data, objectives, criteria)
            for data in self.dataset
        ]
        # Filter out None prompts to satisfy type checker
        filtered_prompts = [p for p in prompts if p is not None]
        responses = await self._batch_inference_with_token_limit(filtered_prompts)
        return responses

    def run_inference(self, objectives: List[str], criteria: str) -> List[Optional[dict]]:
        return asyncio.run(self.llm_inference(objectives, criteria))

    @staticmethod
    def response_to_dataframe(responses: List[Optional[dict]], dataset: List[str]) -> pd.DataFrame:
        results = []
        for i, response in enumerate(responses):
            if response is None:
                continue
            try:
                content = response["choices"][0]["message"]["content"].strip().split("\n")
                decision = content[-1]
                reasoning = "\n".join(content[:-1])
                study_id = i + 1
                results.append({
                    "id": study_id,
                    "text": dataset[i],
                    "reasoning": reasoning,
                    "decision": decision,
                })
            except Exception as e:
                print(f"Error parsing response index {i}: {e}")
        df = pd.DataFrame(results)
        df["label"] = df["decision"].apply(lambda x: 0 if "XXX" in x else 1)
        return df

