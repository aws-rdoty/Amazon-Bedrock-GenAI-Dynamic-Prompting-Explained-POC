import os
from dotenv import load_dotenv
import boto3
import json
import botocore.config
import yaml
from langchain.prompts.few_shot import FewShotPromptTemplate
from langchain.prompts.prompt import PromptTemplate
from langchain.embeddings.huggingface import HuggingFaceEmbeddings
from langchain.prompts.example_selector.semantic_similarity import (
    SemanticSimilarityExampleSelector,
)
from langchain.vectorstores import Chroma

# loading in environment variables
load_dotenv()

# configuring our CLI profile name
boto3.setup_default_session(profile_name=os.getenv('profile_name'))
# increasing the timeout period when invoking bedrock
config = botocore.config.Config(connect_timeout=120, read_timeout=120)
# instantiating the bedrock client
bedrock = boto3.client('bedrock-runtime', 'us-east-1', endpoint_url='https://bedrock-runtime.us-east-1.amazonaws.com',
                       config=config)


def load_samples():
    """
    Load the generic examples for few-shot prompting.
    :return: The generic samples from the generic_samples.yaml file
    """
    # initializing the generic_samples variable, where we will store our samples once they are read in
    generic_samples = None
    # opening and reading the sample prompts file
    with open("sample_prompts/generic_samples.yaml", "r") as stream:
        # storing the sample files in the generic samples variable we initialized
        generic_samples = yaml.safe_load(stream)
    # returning the string containing all the sample prompts
    return generic_samples


def chat_history_loader():
    """
    This function reads the chat_history.txt file, and puts it into a string to later inject into our prompt.
    :return: A string containing all the chat history question and answers in a prompt format.
    """
    # opening the chat history txt file
    with open("chat_history.txt", "r") as file:
        # reading the contents of the chat_history.txt file and reading it into a string
        chat_history = file.read()
        # simple logic if there is no Chat History return None
        if chat_history == "":
            return None
        # if there is Chat History, return it so it can be formatted in the final prompt
        else:
            return chat_history


def prompt_finder(question):
    """
    This function performs a semantic search based on the users question against all the sample prompts stored in the
    sample_prompts/generic_samples.yaml file. It finds the three most relevant prompts and formats them into a single prompt
    along with the users question.
    :param question: This is the question that is passed in through the streamlit frontend from the user.
    :return: This function returns a final prompt that contains three semantically similar prompts, the chat history if
    there is any and the users question all formatted in a single prompt ready to be passed into Amazon Bedrock. We also return
    a formatted string containing all of the prompts used for that particular question.
    """
    # loading the sample prompts from sample_prompts/generic_samples.yaml
    examples = load_samples()
    # instantiating the hugging face embeddings model to be used to produce embeddings of user queries and prompts
    local_embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    # The example selector loads the examples, creates the embeddings, stores them in Chroma (vector store) and a
    # semantic search is performed to see the similarity between the question and prompts, it returns the 3 most similar
    # prompts as defined by k
    example_selector = SemanticSimilarityExampleSelector.from_examples(
        # This is the list of examples available to select from.
        examples,
        # This is the embedding class used to produce embeddings which are used to measure semantic similarity.
        local_embeddings,
        # This is the VectorStore class that is used to store the embeddings and do a similarity search over.
        Chroma,
        # This is the number of examples to produce.
        # TODO: Can change this number to determine how many prompts you want to retrieve
        k=3
    )
    # This is formatting the prompts that are retrieved from the sample_prompts/generic_samples.yaml file
    example_prompt = PromptTemplate(input_variables=["input", "answer"], template="\n\nHuman: {input} \n\nAssistant: "
                                                                                  "{answer}")
    # This is orchestrating the example selector (finding similar prompts to the question), example_prompt (formatting
    # the retrieved prompts, and formatting the chat history and the user input
    prompt = FewShotPromptTemplate(
        example_selector=example_selector,
        example_prompt=example_prompt,
        suffix=f"Chat History: {chat_history_loader()}\n\n" + "Human: {input}\n\nAssistant:",
        input_variables=["input"]
    )
    # This is calling the prompt method and passing in the users question to create the final multi-shot prompt,
    # with the semantically similar prompts, and chat history
    question_with_prompt = prompt.format(input=question)
    # storing the generated prompt
    text = question_with_prompt
    # parsing out the selected prompts, specifically parsing everything before Chat History
    head, sep, tail = text.partition("Chat History:")
    # splitting up the used prompts into an array to better format them
    used_prompts = head.split("\n\n")
    # looping through the array and removing any values that are blank spaces from when we performed a split
    for index, i in enumerate(used_prompts):
        # if the value is an empty string, we choose to remove it
        if i == "":
            # removing the blank value from the list
            used_prompts.remove(i)
    # formatting the prompts and storing them as variables, each contains the Question and Answer used for the prompt
    prompt_one = f"""
    
    {used_prompts[0]}
    
    {used_prompts[1]}
    """
    prompt_two = f"""
    
    {used_prompts[2]}
    
    {used_prompts[3]}
    """
    prompt_three = f"""
    
    {used_prompts[4]}
    
    {used_prompts[5]}
    """
    # formatting all the selected prompts as a single string for easier formatting
    selected_prompts = f"""
    Prompt 1:
    
    {prompt_one}
    
    Prompt 2: 
    
    {prompt_two}
     
    Prompt 3:
    
    {prompt_three}
    """
    # we return the finalized prompt, ready to be passed into Amazon Bedrock to generate a response, along with a string containing
    # the dynamically selected prompts
    return llm_answer_generator(question_with_prompt), selected_prompts


def llm_answer_generator(question_with_prompt):
    """
    This function is used to invoke Amazon Bedrock using the finalized prompt that was created by the prompt_finder(question)
    function.
    :param question_with_prompt: This is the finalized prompt that includes semantically similar prompts, chat history,
    and the users question all in a proper multi-shot format.
    :return: The final answer to the users question.
    """
    # body of data with parameters that is passed into the bedrock invoke model request
    # TODO: TUNE THESE PARAMETERS AS YOU SEE FIT
    body = json.dumps({"prompt": question_with_prompt,
                       "max_tokens_to_sample": 8191,
                       "temperature": 0,
                       "top_k": 250,
                       "top_p": 0.5,
                       "stop_sequences": []
                       })
    # configure model specifics such as specific model
    modelId = 'anthropic.claude-v2'
    accept = 'application/json'
    contentType = 'application/json'
    # Invoking the bedrock model with your specifications
    response = bedrock.invoke_model(body=body,
                                    modelId=modelId,
                                    accept=accept,
                                    contentType=contentType)
    # the body of the response that was generated
    response_body = json.loads(response.get('body').read())
    # retrieving the specific completion field, where you answer will be
    answer = response_body.get('completion')
    # returning the answer as a final result, which ultimately gets returned to the end user
    return answer
