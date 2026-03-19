#!/bin/bash
# test_vectordb.sh - Vector Database 完整測試腳本
#
# 這個腳本會依序執行所有測試，幫你檢查 vector database 是否正常
#
# 使用方式：
#   chmod +x test_vectordb.sh
#   ./test_vectordb.sh

# 顏色定義
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 專案目錄
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# 啟動虛擬環境
if [ -f "venv/bin/activate" ]; then
    echo -e "${BLUE}啟動虛擬環境...${NC}"
    source venv/bin/activate
else
    echo -e "${RED}錯誤：找不到虛擬環境 venv/${NC}"
    exit 1
fi

echo ""
echo "========================================"
echo "  Vector Database 測試腳本"
echo "========================================"
echo ""

# 測試 1：檢查資料庫狀態
echo -e "${GREEN}=== 測試 1: 檢查資料庫狀態 ===${NC}"
python scripts/inspect_vectordb.py stats

# 檢查是否有資料
DB_COUNT=$(python scripts/inspect_vectordb.py stats 2>&1 | grep "總文件數:" | grep -o "[0-9]*")

if [ "$DB_COUNT" -eq 0 ]; then
    echo ""
    echo -e "${YELLOW}⚠️  資料庫是空的！${NC}"
    echo -e "${YELLOW}是否要執行資料抓取？(y/n)${NC}"
    read -r RESPONSE
    
    if [ "$RESPONSE" = "y" ] || [ "$RESPONSE" = "Y" ]; then
        echo -e "${BLUE}執行資料抓取...${NC}"
        python scripts/ingest_all.py
        echo ""
        echo -e "${GREEN}資料抓取完成！重新檢查狀態...${NC}"
        python scripts/inspect_vectordb.py stats
    else
        echo -e "${YELLOW}跳過資料抓取，繼續測試...${NC}"
    fi
fi

echo ""
echo -e "${GREEN}=== 測試 2: 瀏覽資料內容 ===${NC}"
echo -e "${BLUE}顯示每個 collection 的前 2 筆資料...${NC}"
python scripts/inspect_vectordb.py browse --limit 2

echo ""
echo -e "${GREEN}=== 測試 3: 測試查詢功能 ===${NC}"

# 測試查詢 1
echo ""
echo -e "${BLUE}查詢 1: Lakers injury update${NC}"
python scripts/inspect_vectordb.py test-query --q "Lakers injury update" --k 3

# 測試查詢 2
echo ""
echo -e "${BLUE}查詢 2: Who is questionable?${NC}"
python scripts/inspect_vectordb.py test-query --q "Who is questionable?" --k 3

# 測試查詢 3
echo ""
echo -e "${BLUE}查詢 3: Anthony Davis status${NC}"
python scripts/inspect_vectordb.py test-query --q "Anthony Davis status" --k 3

echo ""
echo -e "${GREEN}=== 測試 4: 視覺化（可選）===${NC}"
echo -e "${YELLOW}是否要生成向量視覺化圖表？(y/n)${NC}"
echo -e "${YELLOW}(需要安裝 matplotlib 和 scikit-learn)${NC}"
read -r RESPONSE

if [ "$RESPONSE" = "y" ] || [ "$RESPONSE" = "Y" ]; then
    echo -e "${BLUE}生成視覺化圖表...${NC}"
    
    # 檢查是否安裝了必要的套件
    if python -c "import matplotlib, sklearn" 2>/dev/null; then
        python scripts/inspect_vectordb.py visualize --method tsne --output test_vectors.png
        echo -e "${GREEN}✓ 圖表已儲存: test_vectors.png${NC}"
    else
        echo -e "${RED}錯誤：需要安裝 matplotlib 和 scikit-learn${NC}"
        echo -e "${YELLOW}執行: pip install matplotlib scikit-learn${NC}"
    fi
else
    echo -e "${YELLOW}跳過視覺化${NC}"
fi

echo ""
echo "========================================"
echo -e "${GREEN}  測試完成！${NC}"
echo "========================================"
echo ""
echo "測試結果摘要："
echo "  1. 資料庫狀態：已檢查"
echo "  2. 資料內容：已瀏覽"
echo "  3. 查詢功能：已測試 3 個查詢"
echo "  4. 視覺化：$([ "$RESPONSE" = "y" ] && echo '已生成' || echo '已跳過')"
echo ""
echo "詳細文檔："
echo "  - 完整使用指南: docs/VECTORDB_TESTING.md"
echo "  - 快速入門: docs/QUICK_START_TESTING.md"
echo ""

