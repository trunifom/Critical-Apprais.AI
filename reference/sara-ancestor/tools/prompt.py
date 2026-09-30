import json

class PromptGenerator:
    """
    A class to generate prompts for the model based on the text type (abstract or fulltext), objectives, inclusion and exclusion criteria.

    Attributes:
    prompts_path (str): The path to the JSON file containing the prompts.
    dataset (list): A list of abstracts or fulltexts.
    prompts (dict): A dictionary containing the prompts loaded from the JSON file.

    Methods:
    load_prompts(file_path): Load the prompts from the JSON file.
    abstract_prompt(abstract, objectives, inclusion_criteria, exclusion_criteria): Generate a prompt for abstracts.
    fulltext_prompt(fulltext, objectives, inclusion_criteria, exclusion_criteria): Generate a prompt for fulltexts.

    """


    def __init__(self, prompts_path, prompt_type):
        self.prompt_type = prompt_type
        self.prompts = self.load_prompts(prompts_path)
    
    def load_prompts(self, file_path):
        """
        Load the prompts from the JSON file.

        Args:
        file_path (str): The path to the JSON file containing the prompts.

        Returns:
        dict: A dictionary containing the prompts loaded from the JSON file.
        """
        try:
            with open(file_path, 'r') as file:
                prompts = json.load(file)[self.prompt_type]
            return prompts
        except FileNotFoundError:
            print(f"Error: The file {file_path} was not found.")
            return {}
        except json.JSONDecodeError:
            print(f"Error: The file {file_path} is not a valid JSON.")
            return {}
    
    def abstract_prompt(self, abstract, objectives, inclusion_criteria, exclusion_criteria):
        """
        Generate a prompt for abstracts.

        Args:
        abstract (str): Abstract text.
        objectives (list): A list of objectives for the review.
        inclusion_criteria (list): A list of inclusion criteria.
        exclusion_criteria (list): A list of exclusion criteria.

        Returns:
        str: A prompt for the model.
        """
        objectives_text = "\n".join([f"(i) {objective}" for objective in objectives])
        inclusion_criteria_text = "\n".join([f"- {criterion}" for criterion in inclusion_criteria])
        exclusion_criteria_text = "\n".join([f"- {criterion}" for criterion in exclusion_criteria])
        
        prompt = (
            "Our scoping or systematic review is governed by the following objectives: \n"
            f"{objectives_text}\n\n"
            f"{self.prompts.get('pre_prompt', '')}\n\n"
            f"Inclusion Criteria:\n{inclusion_criteria_text}\n\n"
            f"Exclusion Criteria:\n{exclusion_criteria_text}\n\n"
            f"Abstract: {abstract}\n\n"
            f"{self.prompts.get('instructions', '')}"
        )
        
        return prompt
    
    def fulltext_prompt(self, fulltext, objectives, inclusion_criteria, exclusion_criteria):
        # Implement this method if needed
        pass