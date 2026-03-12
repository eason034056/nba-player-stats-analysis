#!/usr/bin/env python3
"""
inspect_vectordb.py - Vector Database 檢查和視覺化工具

這個腳本提供多種方式來檢查和視覺化 vector database 的內容：

1. 顯示統計資訊 (stats)
   - 每個 collection 的文件數量
   - 資料庫大小

2. 瀏覽資料內容 (browse)
   - 查看實際存儲的文字
   - 檢查 metadata

3. 視覺化向量 (visualize)
   - 使用 t-SNE 或 PCA 降維
   - 在 2D 平面上顯示向量分佈
   - 不同 collection 用不同顏色

4. 測試查詢 (test-query)
   - 驗證語意搜索是否正常
   - 顯示查詢結果

使用方式：
    # 顯示統計資訊
    python scripts/inspect_vectordb.py stats
    
    # 瀏覽資料（預設顯示前 10 筆）
    python scripts/inspect_vectordb.py browse --collection nba_news --limit 5
    
    # 視覺化向量
    python scripts/inspect_vectordb.py visualize --method tsne
    
    # 測試查詢
    python scripts/inspect_vectordb.py test-query --q "Lakers injury"

命名說明：
- show_stats(): 顯示資料庫統計
- browse_data(): 瀏覽實際資料內容
- visualize_vectors(): 視覺化向量分佈
- test_query(): 測試查詢功能
"""

import sys
from pathlib import Path

# 將專案根目錄加入 Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import argparse
import json
from typing import List, Dict, Any, Optional
import numpy as np

from src.vectordb.collections import get_collection_manager, COLLECTION_CONFIGS
from src.vectordb.query import QueryEngine
from src.logging_utils import get_logger

logger = get_logger("inspect_vectordb")


def show_stats():
    """
    顯示 vector database 的統計資訊
    
    包含：
    - 每個 collection 的文件數量
    - 總文件數量
    - Collection 配置資訊
    
    使用方式：
        python scripts/inspect_vectordb.py stats
    """
    logger.info("=== Vector Database 統計資訊 ===\n")
    
    # 獲取 collection manager
    manager = get_collection_manager()
    
    # 獲取統計資訊
    # CollectionManager.get_stats() 返回格式：
    # {
    #   "nba_news": {"count": 436, "priority": 3},
    #   "nba_injury_reports": {"count": 0, ...},
    #   ...
    # }
    stats = manager.get_stats()
    
    total_docs = 0
    
    # 顯示每個 collection 的資訊
    logger.info(f"Collections 總數: {len(COLLECTION_CONFIGS)}\n")
    
    for name, config in COLLECTION_CONFIGS.items():
        # 獲取該 collection 的統計
        # stats 直接就是 {name: {count: int}} 結構
        coll_stats = stats.get(name, {})
        count = coll_stats.get("count", 0)
        total_docs += count
        
        # 狀態標記
        status = "✓" if count > 0 else "✗ (空)"
        
        # 顯示資訊
        logger.info(f"Collection: {name}")
        logger.info(f"  描述: {config.description}")
        logger.info(f"  文件數量: {count:,} {status}")
        logger.info(f"  優先順序: {config.priority}")
        logger.info(f"  預設查詢數: {config.default_top_k}")
        logger.info("")
    
    # 總結
    logger.info("=" * 60)
    logger.info(f"總文件數: {total_docs:,}")
    
    if total_docs == 0:
        logger.warning("\n⚠️  警告：資料庫是空的！")
        logger.warning("請先執行以下指令來抓取資料：")
        logger.warning("  python scripts/ingest_all.py")
    else:
        logger.info("✓ 資料庫包含資料")
    
    logger.info("=" * 60)


def browse_data(
    collection_name: str = None,
    limit: int = 10,
    show_embeddings: bool = False,
):
    """
    瀏覽 vector database 中的實際資料
    
    顯示：
    - 文件 ID
    - 文字內容
    - Metadata
    - (可選) Embeddings
    
    Args:
        collection_name: 要瀏覽的 collection 名稱（不指定則瀏覽所有）
        limit: 每個 collection 顯示的文件數量
        show_embeddings: 是否顯示 embedding 向量
    
    使用方式：
        # 瀏覽所有 collections
        python scripts/inspect_vectordb.py browse
        
        # 瀏覽特定 collection
        python scripts/inspect_vectordb.py browse --collection nba_news --limit 5
    """
    logger.info("=== 瀏覽 Vector Database 內容 ===\n")
    
    manager = get_collection_manager()
    
    # 決定要瀏覽的 collections
    if collection_name:
        collections = [collection_name]
    else:
        collections = list(COLLECTION_CONFIGS.keys())
    
    for coll_name in collections:
        logger.info(f"\n{'=' * 60}")
        logger.info(f"Collection: {coll_name}")
        logger.info("=" * 60)
        
        try:
            collection = manager.get_collection(coll_name)
            
            # 獲取資料
            # ChromaDB 的 get() 方法：
            # - ids: 要獲取的文件 ID（不指定則獲取全部）
            # - limit: 限制返回數量
            # - include: 要返回的欄位
            results = collection.get(
                limit=limit,
                include=["documents", "metadatas", "embeddings"] if show_embeddings else ["documents", "metadatas"]
            )
            
            # results 結構：
            # {
            #   'ids': ['id1', 'id2', ...],
            #   'documents': ['doc1', 'doc2', ...],
            #   'metadatas': [{...}, {...}, ...],
            #   'embeddings': [[...], [...], ...] (如果 include 了)
            # }
            
            if not results["ids"]:
                logger.warning(f"  此 collection 是空的\n")
                continue
            
            logger.info(f"  總文件數: {collection.count()}")
            logger.info(f"  顯示前 {limit} 筆:\n")
            
            # 遍歷每個文件
            for i, doc_id in enumerate(results["ids"], 1):
                logger.info(f"  [{i}] ID: {doc_id}")
                
                # 文字內容（顯示前 200 字元）
                text = results["documents"][i-1]
                preview = text[:200].replace("\n", " ")
                logger.info(f"      文字: {preview}...")
                logger.info(f"      (完整長度: {len(text)} 字元)")
                
                # Metadata
                metadata = results["metadatas"][i-1]
                logger.info(f"      Metadata:")
                for key, value in metadata.items():
                    # 格式化顯示（縮短長字串）
                    if isinstance(value, str) and len(value) > 50:
                        value = value[:50] + "..."
                    logger.info(f"        {key}: {value}")
                
                # Embedding（如果要顯示）
                if show_embeddings:
                    embedding = results["embeddings"][i-1]
                    logger.info(f"      Embedding: {len(embedding)} 維向量")
                    logger.info(f"        前 5 維: {embedding[:5]}")
                
                logger.info("")
            
        except Exception as e:
            logger.error(f"  錯誤: {e}\n")


def visualize_vectors(
    method: str = "tsne",
    sample_size: int = 500,
    output_file: str = None,
):
    """
    視覺化 vector database 中的向量
    
    將高維向量（通常是 384 或 768 維）降維到 2D，
    然後在平面上顯示，不同 collection 用不同顏色
    
    Args:
        method: 降維方法 ("tsne" 或 "pca")
        sample_size: 每個 collection 取樣數量（避免資料太多）
        output_file: 輸出圖片檔案名稱（不指定則顯示在螢幕上）
    
    使用方式：
        # 使用 t-SNE
        python scripts/inspect_vectordb.py visualize --method tsne
        
        # 使用 PCA 並儲存圖片
        python scripts/inspect_vectordb.py visualize --method pca --output vectors.png
    
    說明：
    - t-SNE: 保留局部結構，適合看聚類
    - PCA: 保留全域結構，速度較快
    """
    logger.info(f"=== 視覺化向量（使用 {method.upper()}）===\n")
    
    try:
        import matplotlib.pyplot as plt
        from sklearn.manifold import TSNE
        from sklearn.decomposition import PCA
    except ImportError:
        logger.error("錯誤：需要安裝 matplotlib 和 scikit-learn")
        logger.error("請執行: pip install matplotlib scikit-learn")
        return
    
    manager = get_collection_manager()
    
    # 收集每個 collection 的向量
    all_embeddings = []
    all_labels = []
    all_colors = []
    
    # 定義顏色
    colors = {
        "nba_injury_reports": "red",
        "nba_injuries_pages": "orange",
        "nba_news": "blue",
    }
    
    logger.info("收集向量資料...")
    
    for coll_name in COLLECTION_CONFIGS.keys():
        try:
            collection = manager.get_collection(coll_name)
            count = collection.count()
            
            if count == 0:
                logger.warning(f"  {coll_name}: 空的，跳過")
                continue
            
            # 決定取樣數量
            fetch_limit = min(sample_size, count)
            
            logger.info(f"  {coll_name}: 取樣 {fetch_limit}/{count} 個向量")
            
            # 獲取資料（包含 embeddings）
            results = collection.get(
                limit=fetch_limit,
                include=["embeddings"]
            )
            
            # 收集向量
            embeddings = np.array(results["embeddings"])
            all_embeddings.append(embeddings)
            
            # 標記來源
            all_labels.extend([coll_name] * len(embeddings))
            all_colors.extend([colors.get(coll_name, "gray")] * len(embeddings))
            
        except Exception as e:
            logger.error(f"  {coll_name}: 錯誤 - {e}")
    
    if not all_embeddings:
        logger.error("沒有可視覺化的資料")
        return
    
    # 合併所有向量
    all_embeddings = np.vstack(all_embeddings)
    logger.info(f"\n總共 {len(all_embeddings)} 個向量，維度: {all_embeddings.shape[1]}")
    
    # 降維
    logger.info(f"執行 {method.upper()} 降維...")
    
    if method.lower() == "tsne":
        # t-SNE: 非線性降維，保留局部結構
        # perplexity: 控制關注的鄰居數量（5-50）
        # n_iter: 迭代次數
        reducer = TSNE(
            n_components=2,
            perplexity=30,
            n_iter=1000,
            random_state=42
        )
    elif method.lower() == "pca":
        # PCA: 線性降維，保留全域結構
        reducer = PCA(n_components=2, random_state=42)
    else:
        logger.error(f"不支援的方法: {method}")
        return
    
    # 執行降維
    vectors_2d = reducer.fit_transform(all_embeddings)
    
    logger.info("繪製圖表...")
    
    # 繪圖
    plt.figure(figsize=(12, 8))
    
    # 為每個 collection 繪製散點圖
    for coll_name, color in colors.items():
        # 找出屬於這個 collection 的點
        mask = np.array([label == coll_name for label in all_labels])
        
        if mask.sum() > 0:
            plt.scatter(
                vectors_2d[mask, 0],
                vectors_2d[mask, 1],
                c=color,
                label=coll_name,
                alpha=0.6,
                s=50
            )
    
    plt.title(f"Vector Database 向量視覺化 ({method.upper()})", fontsize=16)
    plt.xlabel("維度 1", fontsize=12)
    plt.ylabel("維度 2", fontsize=12)
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    # 儲存或顯示
    if output_file:
        plt.savefig(output_file, dpi=150, bbox_inches='tight')
        logger.info(f"✓ 圖表已儲存: {output_file}")
    else:
        logger.info("顯示圖表（關閉視窗以繼續）...")
        plt.show()


def test_query(question: str, team: str = None, top_k: int = 5):
    """
    測試查詢功能
    
    Args:
        question: 查詢問題
        team: 球隊過濾（可選）
        top_k: 返回結果數量
    
    使用方式：
        python scripts/inspect_vectordb.py test-query --q "Lakers injury"
        python scripts/inspect_vectordb.py test-query --q "Who is out?" --team LAL
    """
    logger.info("=== 測試查詢功能 ===\n")
    
    logger.info(f"查詢: {question}")
    if team:
        logger.info(f"過濾: team={team}")
    logger.info("")
    
    engine = QueryEngine()
    
    try:
        results = engine.query(
            question=question,
            team=team,
            top_k=top_k
        )
        
        if not results:
            logger.warning("沒有找到結果")
            return
        
        logger.info(f"找到 {len(results)} 個結果:\n")
        
        for i, r in enumerate(results, 1):
            logger.info(f"[{i}] 分數: {r.score:.4f} | Collection: {r.collection}")
            
            # Metadata
            meta = r.metadata
            if meta.get("team"):
                logger.info(f"    球隊: {meta.get('team')}")
            if meta.get("player_names"):
                # player_names 可能是字串（逗號分隔）或 list
                # 因為我們在 upsert 時把 list 轉成了字串
                player_names = meta.get("player_names")
                if isinstance(player_names, str):
                    # 如果是字串，直接顯示（已經是逗號分隔的格式）
                    logger.info(f"    球員: {player_names}")
                else:
                    # 如果是 list，用逗號連接
                    logger.info(f"    球員: {', '.join(player_names)}")
            if meta.get("title"):
                logger.info(f"    標題: {meta.get('title')[:60]}...")
            
            # 內容預覽
            preview = r.text[:200].replace("\n", " ")
            logger.info(f"    內容: {preview}...")
            logger.info("")
        
        logger.info("✓ 查詢測試完成")
        
    except Exception as e:
        logger.error(f"查詢失敗: {e}")


def export_collection(collection_name: str, output_file: str):
    """
    匯出 collection 的所有資料到 JSON 檔案
    
    Args:
        collection_name: collection 名稱
        output_file: 輸出檔案路徑
    
    使用方式：
        python scripts/inspect_vectordb.py export --collection nba_news --output data.json
    """
    logger.info(f"=== 匯出 Collection: {collection_name} ===\n")
    
    manager = get_collection_manager()
    
    try:
        collection = manager.get_collection(collection_name)
        count = collection.count()
        
        logger.info(f"Collection 包含 {count} 個文件")
        logger.info("讀取資料...")
        
        # 獲取所有資料
        results = collection.get(
            include=["documents", "metadatas"]
        )
        
        # 整理成易讀格式
        data = []
        for i, doc_id in enumerate(results["ids"]):
            data.append({
                "id": doc_id,
                "text": results["documents"][i],
                "metadata": results["metadatas"][i],
            })
        
        # 寫入 JSON 檔案
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"✓ 已匯出 {len(data)} 個文件到: {output_file}")
        
    except Exception as e:
        logger.error(f"匯出失敗: {e}")


def main():
    """
    主程式入口
    """
    parser = argparse.ArgumentParser(
        description="Vector Database 檢查和視覺化工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例：

1. 顯示統計資訊：
    python scripts/inspect_vectordb.py stats

2. 瀏覽資料：
    python scripts/inspect_vectordb.py browse
    python scripts/inspect_vectordb.py browse --collection nba_news --limit 5

3. 視覺化向量：
    python scripts/inspect_vectordb.py visualize --method tsne
    python scripts/inspect_vectordb.py visualize --method pca --output vectors.png

4. 測試查詢：
    python scripts/inspect_vectordb.py test-query --q "Lakers injury"
    python scripts/inspect_vectordb.py test-query --q "Who is out?" --team LAL

5. 匯出資料：
    python scripts/inspect_vectordb.py export --collection nba_news --output data.json
        """
    )
    
    # 子命令
    subparsers = parser.add_subparsers(dest="command", help="要執行的操作")
    
    # stats 命令
    parser_stats = subparsers.add_parser("stats", help="顯示統計資訊")
    
    # browse 命令
    parser_browse = subparsers.add_parser("browse", help="瀏覽資料內容")
    parser_browse.add_argument("--collection", type=str, help="Collection 名稱")
    parser_browse.add_argument("--limit", type=int, default=10, help="顯示數量")
    parser_browse.add_argument("--show-embeddings", action="store_true", help="顯示 embedding 向量")
    
    # visualize 命令
    parser_viz = subparsers.add_parser("visualize", help="視覺化向量")
    parser_viz.add_argument("--method", choices=["tsne", "pca"], default="tsne", help="降維方法")
    parser_viz.add_argument("--sample-size", type=int, default=500, help="每個 collection 取樣數量")
    parser_viz.add_argument("--output", type=str, help="輸出圖片檔案")
    
    # test-query 命令
    parser_query = subparsers.add_parser("test-query", help="測試查詢")
    parser_query.add_argument("--q", "--query", type=str, required=True, help="查詢問題")
    parser_query.add_argument("--team", type=str, help="球隊過濾")
    parser_query.add_argument("--k", type=int, default=5, help="返回數量")
    
    # export 命令
    parser_export = subparsers.add_parser("export", help="匯出資料")
    parser_export.add_argument("--collection", type=str, required=True, help="Collection 名稱")
    parser_export.add_argument("--output", type=str, required=True, help="輸出檔案")
    
    args = parser.parse_args()
    
    # 執行對應的命令
    if args.command == "stats":
        show_stats()
    
    elif args.command == "browse":
        browse_data(
            collection_name=args.collection,
            limit=args.limit,
            show_embeddings=args.show_embeddings,
        )
    
    elif args.command == "visualize":
        visualize_vectors(
            method=args.method,
            sample_size=args.sample_size,
            output_file=args.output,
        )
    
    elif args.command == "test-query":
        test_query(
            question=args.q,
            team=args.team,
            top_k=args.k,
        )
    
    elif args.command == "export":
        export_collection(
            collection_name=args.collection,
            output_file=args.output,
        )
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

