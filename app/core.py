import os
import timeit

import pandas as pd
import qdrant_client
from dotenv import load_dotenv

# from langchain.embeddings.huggingface import HuggingFaceEmbeddings
from langchain_community.embeddings import HuggingFaceEmbeddings

# from langchain_huggingface import HuggingFaceEmbeddings
from llama_index.core import Settings, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.embeddings.langchain import LangchainEmbedding
from llama_index.llms.ollama import Ollama
from llama_index.llms.openai import OpenAI
from llama_index.vector_stores.qdrant import QdrantVectorStore

from app import app
from app.support import (
    generate_queries,
    get_filters_qdrant,
    get_filters_qdrant_filtered,
    refine_template,
    text_qa_template,
)

load_dotenv()
# pip install cohere

cohere_api_key = os.getenv("COHERE_API_KEY")

index_name = os.getenv("INDEX_NAME")
URI_BD = os.getenv("URI_BD")
LLM_URL = os.getenv("LLM_URL")
OPENAI_KEY = os.getenv("OPENAI_KEY")
# client = OpenAI(
#    # This is the default and can be omitted
#    api_key=os.getenv("OPENAI_KEY"),
# )
metadatasource = pd.read_csv("finaldbpt2.csv", delimiter=",")
embed_model_name = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
embed_model_name = "sentence-transformers/all-mpnet-base-v2"
client = qdrant_client.QdrantClient(URI_BD)


def retrieve_index(client, llm, index_name):
    text_splitter = SentenceSplitter(chunk_size=512, chunk_overlap=10)
    Settings.text_splitter = text_splitter

    # embed_model = OpenAIEmbedding(embed_batch_size=10)
    embed_model = LangchainEmbedding(HuggingFaceEmbeddings(model_name=embed_model_name))
    Settings.llm = llm
    Settings.embed_model = embed_model
    # Settings.num_output = 512
    # Settings.context_window = 3900
    Settings.chunk_size = 1024
    Settings.chunk_overlap = 64

    vector_store = QdrantVectorStore(client=client, collection_name=index_name)
    index = VectorStoreIndex.from_vector_store(
        vector_store,
        text_qa_template=text_qa_template,
        refine_template=refine_template,
        transformations=[text_splitter],
    )

    return index


def build_rag_pipeline(products, metadatasource, strength=None):
    if OPENAI_KEY is not None:
        llm = OpenAI(temperature=0, api_key=OPENAI_KEY, model="gpt-4")
    else:
        # pass
        llm = Ollama(
            model="llama3.1:70b",
            base_url=LLM_URL,
            temperature=0,
            request_timeout=120,
        )
    print("Building index...")
    index = retrieve_index(client, llm, index_name)
    print("Constructing query engine...")
    if strength:  # demo
        filters_qdrant = get_filters_qdrant_filtered(
            products=products, metadatasource=metadatasource, strength=strength
        )
    else:  # not demo
        filters_qdrant = get_filters_qdrant(
            products=products, metadatasource=metadatasource
        )
    print("filtro", filters_qdrant)
    app.logger.info("Filtros: {}".format(filters_qdrant))

    results = client.search(
        collection_name=index_name,
        query_vector=[0.1] * 768,
        limit=10,
        query_filter=filters_qdrant,
    )

    # Check if results are found
    if len(results) == 0:
        print("issue with the product and data in the collection")
        filters_qdrant = None
    retriever = VectorIndexRetriever(
        vector_store_kwargs={"qdrant_filters": filters_qdrant},
        index=index,
        # filters=filters,
        similarity_top_k=10,
    )
    # configure response synthesizer
    # response_synthesizer = get_response_synthesizer()
    # reranker = SentenceTransformerRerank(
    #    model="cross-encoder/ms-marco-MiniLM-L-2-v2", top_n=15
    # )
    # reranker = CohereRerank(api_key=cohere_api_key, top_n=7)
    # assemble query engine
    query_engine = RetrieverQueryEngine(
        retriever=retriever,  # response_mode="compact",
        #  node_postprocessors=[
        #       reranker
        #   ],  # ,SimilarityPostprocessor(similarity_cutoff=0.7)],
    )

    query_engine.update_prompts(
        {
            "response_synthesizer:text_qa_template": text_qa_template,
            "response_synthesizer:refine_template": refine_template,
        }
    )

    return query_engine


def present_result(query):
    start = timeit.default_timer()

    products, add_info = generate_queries(query)

    print("Detected products:", products)
    rag_chain = build_rag_pipeline(products=products, metadatasource=metadatasource)
    nquery = (
        query
        + "\n---------\nContext and more information about the products:\n"
        + add_info
    )

    app.logger.info("Pergunta melhorada: {}".format(nquery))

    answer = rag_chain.query(nquery)
    end = timeit.default_timer()

    return {
        "response": answer.response,
        "metadata": answer.metadata,
        "time": str(round(end - start)) + "s",
    }


def present_result_filtered(query, product, dosagem):
    start = timeit.default_timer()

    # _, add_info = generate_queries(query)

    # print("Detected products:", products)
    rag_chain = build_rag_pipeline(
        products=product, metadatasource=metadatasource, strength=dosagem
    )
    # nquery = (
    #     query
    #     + "\n---------\nContext and more information about the products:\n"
    #     + add_info
    # )

    app.logger.info("Pergunta melhorada: {}".format(query))

    answer = rag_chain.query(query)
    end = timeit.default_timer()

    return {
        "response": answer.response,
        "metadata": answer.metadata,
        "time": str(round(end - start)) + "s",
    }
