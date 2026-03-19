#!/usr/bin/env python3
"""
inspect_example.py - 示範如何用程式碼檢查 vector database

這個範例展示如何在 Python 代碼中直接檢查和使用 vector database

使用方式：
    python examples/inspect_example.py
"""

import sys
from pathlib import Path

# 加入專案路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.vectordb.collections import get_collection_manager
from src.vectordb.query import QueryEngine
from src.logging_utils import get_logger

logger = get_logger("inspect_example")


def example_1_check_stats():
    """
    範例 1：檢查資料庫統計
    
    說明：
    - get_collection_manager(): 獲取 collection 管理器
    - get_stats(): 獲取統計資訊
    """
    logger.info("=== 範例 1：檢查資料庫統計 ===\n")
    
    # 獲取 collection manager
    manager = get_collection_manager()
    
    # 獲取統計資訊
    stats = manager.get_stats()
    
    # 顯示結果
    logger.info(f"Collections 總數: {stats['total_collections']}")
    
    total_docs = 0
    for name, info in stats['collections'].items():
        count = info['count']
        total_docs += count
        logger.info(f"  {name}: {count} 個文件")
    
    logger.info(f"\n總文件數: {total_docs}\n")


def example_2_browse_collection():
    """
    範例 2：瀏覽 collection 的內容
    
    說明：
    - get_collection(): 獲取特定 collection
    - collection.get(): 獲取資料
        - limit: 限制數量
        - include: 要返回的欄位
    """
    logger.info("=== 範例 2：瀏覽 collection 內容 ===\n")
    
    manager = get_collection_manager()
    
    # 獲取 nba_news collection
    try:
        collection = manager.get_collection("nba_news")
        logger.info(f"Collection: {collection.name}")
        logger.info(f"文件總數: {collection.count()}\n")
        
        # 獲取前 3 筆資料
        # include 參數指定要返回的欄位：
        # - "documents": 文字內容
        # - "metadatas": metadata
        # - "embeddings": 向量（可選，通常不需要）
        results = collection.get(
            limit=3,
            include=["documents", "metadatas"]
        )
        
        # results 的結構：
        # {
        #   'ids': ['id1', 'id2', ...],
        #   'documents': ['doc1', 'doc2', ...],
        #   'metadatas': [{...}, {...}, ...]
        # }
        
        if results["ids"]:
            logger.info(f"顯示前 {len(results['ids'])} 筆:\n")
            
            for i, doc_id in enumerate(results["ids"], 1):
                logger.info(f"[{i}] ID: {doc_id}")
                
                # 文字內容
                text = results["documents"][i-1]
                preview = text[:100].replace("\n", " ")
                logger.info(f"    文字: {preview}...")
                
                # Metadata
                metadata = results["metadatas"][i-1]
                logger.info(f"    Team: {metadata.get('team', 'N/A')}")
                logger.info(f"    Published: {metadata.get('published_at', 'N/A')}")
                logger.info("")
        else:
            logger.warning("Collection 是空的")
            
    except Exception as e:
        logger.error(f"錯誤: {e}")


def example_3_query():
    """
    範例 3：執行語意查詢
    
    說明：
    - QueryEngine: 查詢引擎
    - query(): 執行查詢
        - question: 查詢問題
        - team: 球隊過濾（可選）
        - player: 球員過濾（可選）
        - top_k: 返回數量
    """
    logger.info("=== 範例 3：執行語意查詢 ===\n")
    
    # 建立查詢引擎
    engine = QueryEngine()
    
    # 執行查詢
    question = "Lakers injury update"
    logger.info(f"查詢: {question}\n")
    
    try:
        # query() 方法會：
        # 1. 將問題轉換成向量
        # 2. 在所有 collections 中搜索
        # 3. 合併和排序結果
        # 4. 返回 QueryResult 列表
        results = engine.query(
            question=question,
            team="LAL",  # 只看 Lakers
            top_k=3
        )
        
        if results:
            logger.info(f"找到 {len(results)} 個結果:\n")
            
            for i, r in enumerate(results, 1):
                # QueryResult 物件包含：
                # - id: chunk ID
                # - text: 文字內容
                # - metadata: 元資料
                # - score: 相似度分數（0-1）
                # - distance: 距離
                # - collection: 來源 collection
                
                logger.info(f"[{i}] 分數: {r.score:.4f}")
                logger.info(f"    來源: {r.collection}")
                logger.info(f"    球隊: {r.metadata.get('team', 'N/A')}")
                
                # 顯示內容預覽
                preview = r.text[:150].replace("\n", " ")
                logger.info(f"    內容: {preview}...")
                logger.info("")
        else:
            logger.warning("沒有找到結果")
            
    except Exception as e:
        logger.error(f"查詢失敗: {e}")


def example_4_filter_by_metadata():
    """
    範例 4：使用 metadata 過濾
    
    說明：
    - collection.get() 的 where 參數可以用來過濾
    - ChromaDB 支援的過濾條件：
        - 簡單條件: {"field": "value"}
        - AND: {"$and": [{...}, {...}]}
        - OR: {"$or": [{...}, {...}]}
    """
    logger.info("=== 範例 4：使用 metadata 過濾 ===\n")
    
    manager = get_collection_manager()
    
    try:
        collection = manager.get_collection("nba_injuries_pages")
        
        # 過濾條件：只看 Lakers
        where_filter = {"team": "LAL"}
        
        logger.info(f"過濾條件: team = LAL\n")
        
        results = collection.get(
            where=where_filter,
            limit=5,
            include=["documents", "metadatas"]
        )
        
        if results["ids"]:
            logger.info(f"找到 {len(results['ids'])} 筆 Lakers 的資料:\n")
            
            for i, doc_id in enumerate(results["ids"], 1):
                metadata = results["metadatas"][i-1]
                text = results["documents"][i-1]
                
                logger.info(f"[{i}] {metadata.get('title', 'N/A')[:50]}")
                logger.info(f"    {text[:100]}...")
                logger.info("")
        else:
            logger.warning("沒有找到符合條件的資料")
            
    except Exception as e:
        logger.error(f"錯誤: {e}")


def example_5_direct_collection_query():
    """
    範例 5：直接對 collection 執行向量查詢
    
    說明：
    - collection.query(): 執行向量查詢
        - query_embeddings: 查詢向量
        - n_results: 返回數量
        - where: metadata 過濾
        - include: 要返回的欄位
    """
    logger.info("=== 範例 5：直接查詢 collection ===\n")
    
    from src.embeddings import embed_query
    
    manager = get_collection_manager()
    
    try:
        collection = manager.get_collection("nba_news")
        
        # 準備查詢
        question = "Who is injured?"
        logger.info(f"查詢: {question}\n")
        
        # 計算查詢向量
        # embed_query() 會將文字轉換成向量
        query_embedding = embed_query(question)
        logger.info(f"查詢向量維度: {len(query_embedding)}")
        
        # 執行查詢
        # query() 方法會找出最相似的向量
        results = collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=3,
            include=["documents", "metadatas", "distances"]
        )
        
        # results 結構：
        # {
        #   'ids': [['id1', 'id2', ...]],
        #   'documents': [['doc1', 'doc2', ...]],
        #   'metadatas': [[{...}, {...}, ...]],
        #   'distances': [[0.1, 0.2, ...]]
        # }
        # 注意：結果是雙層列表（因為可以一次查詢多個向量）
        
        if results["ids"] and results["ids"][0]:
            logger.info(f"\n找到 {len(results['ids'][0])} 個結果:\n")
            
            ids = results["ids"][0]
            documents = results["documents"][0]
            metadatas = results["metadatas"][0]
            distances = results["distances"][0]
            
            for i in range(len(ids)):
                # ChromaDB 使用 L2 距離（越小越相似）
                # 可以轉換成相似度分數：score = 1 / (1 + distance)
                distance = distances[i]
                score = 1 / (1 + distance)
                
                logger.info(f"[{i+1}] 距離: {distance:.4f}, 分數: {score:.4f}")
                logger.info(f"    {documents[i][:100]}...")
                logger.info("")
        else:
            logger.warning("沒有找到結果")
            
    except Exception as e:
        logger.error(f"錯誤: {e}")


def main():
    """
    主程式
    """
    logger.info("\n" + "=" * 60)
    logger.info("Vector Database 檢查範例")
    logger.info("=" * 60 + "\n")
    
    try:
        # 執行所有範例
        example_1_check_stats()
        example_2_browse_collection()
        example_3_query()
        example_4_filter_by_metadata()
        example_5_direct_collection_query()
        
        logger.info("=" * 60)
        logger.info("所有範例執行完成！")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"執行失敗: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

