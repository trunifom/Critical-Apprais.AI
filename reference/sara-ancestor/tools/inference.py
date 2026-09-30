from tools.prompt import PromptGenerator
from tools.llm_providers import get_provider, LLMProviderError
import pandas as pd
from typing import List, Optional


class ModelInference:
    """
    A class to perform inference using an LLM provider (OpenAI, SwissGPT/AlpineAI,
    or Anthropic Claude).

    Attributes:
    prompts_path (str): The path to the JSON file containing the prompts.
    dataset (List[str]): A list of abstracts or fulltexts.
    prompt (PromptGenerator): An instance of the PromptGenerator class.
    provider_name (str): The name of the LLM provider to use ("openai", "swissgpt", or "anthropic").
    data_type (str): The type of data to process (abstracts or fulltexts).
    model (str): The name of the model to use for inference.

    Methods:
    llm_inference(objectives: List[str], inclusion_criteria: List[str], exclusion_criteria: List[str]) -> List[Union[str, None]]: Perform inference using the LLM.
    response_to_dataframe(responses: List[Union[str, None]]) -> pd.DataFrame: Convert the responses to a DataFrame.

    """
    def __init__(self, prompts_path: str, dataset: List[str], token: str, prompt_type: str = "baseline_abstract", data_type: str = "abstracts", model: str = "gpt-4o", provider: str = "openai"):
        self.dataset = dataset
        self.prompt = PromptGenerator(prompts_path, prompt_type)
        self.provider_name = provider
        self._provider = get_provider(provider, token)
        self.data_type = data_type
        self.model = model


    def llm_inference(self, objectives: List[str], inclusion_criteria: List[str], exclusion_criteria: List[str]) -> List[Optional[str]]:
        """ Perform inference using the LLM.

        Args:
        objectives (List[str]): A list of objectives for the review.
        inclusion_criteria (List[str]): A list of inclusion criteria.
        exclusion_criteria (List[str]): A list of exclusion criteria.

        Returns:
        List[Optional[str]]: A list of plain-text responses from the LLM.
        """
        responses = []

        for data in self.dataset:
            if self.data_type == 'abstracts':
                prompt = self.prompt.abstract_prompt(data, objectives, inclusion_criteria, exclusion_criteria)
            elif self.data_type == 'fulltexts':
                prompt = self.prompt.fulltext_prompt(data, objectives, inclusion_criteria, exclusion_criteria)
            else:
                raise ValueError("Invalid type. Choose either 'abstracts' or 'fulltexts'")

            system_prompt = f"You are an expert in systematic and scoping reviews. Your task is to evaluate research {self.data_type} against predefined inclusion and exclusion criteria."

            try:
                text = self._provider.complete(system_prompt=system_prompt, user_prompt=prompt, model=self.model)
                responses.append(text)
            except LLMProviderError as e:
                print(e)
                responses.append(None)

        return responses


    def response_to_dataframe(self, responses: List[Optional[str]]) -> pd.DataFrame:
        """ Convert the responses to a DataFrame.

        Args:
        responses (List[Optional[str]]): A list of plain-text responses from the LLM.

        Returns:
        pd.DataFrame: A DataFrame containing the study ID, study data, reasoning, decision, and label.
        """
        results = []

        for i, response in enumerate(responses):
            if response is None:
                continue

            content = response.strip().split('\n')
            decision = content[-1]
            reasoning = "\n".join(content[:-1])
            study_id = i + 1

            results.append({"id": study_id, f"{self.data_type}": self.dataset[i], "reasoning": reasoning, "decision": decision})

        df = pd.DataFrame(results)
        df['label'] = df['decision'].apply(lambda x: 0 if 'XXX' in x else 1)

        return df
