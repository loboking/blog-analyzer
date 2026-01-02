// 네이버 블로그 통계 분석기 - Popup Script

document.addEventListener('DOMContentLoaded', async () => {
    const loading = document.getElementById('loading');
    const mainContent = document.getElementById('main-content');
    const statusBox = document.getElementById('status-box');
    const statusText = document.getElementById('status-text');
    const statsGrid = document.getElementById('stats-grid');
    const chartSection = document.getElementById('chart-section');
    const topPostsSection = document.getElementById('top-posts-section');
    const exportBtn = document.getElementById('export-btn');

    // 현재 탭 확인
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const url = tab.url || '';

    // 로딩 숨기고 메인 컨텐츠 표시
    loading.style.display = 'none';
    mainContent.style.display = 'block';

    // 네이버 블로그 통계 페이지인지 확인
    const isStatsPage = url.includes('admin.blog.naver.com') ||
                        url.includes('BlogStatistics') ||
                        url.includes('blog.naver.com') && url.includes('admin');

    if (isStatsPage) {
        // 통계 페이지에 있음 - 데이터 가져오기 시도
        statusBox.classList.add('success');
        statusText.innerHTML = '✅ 통계 페이지 감지됨<br><small>데이터를 분석 중입니다...</small>';

        try {
            // content script에 메시지 보내서 데이터 요청
            const response = await chrome.tabs.sendMessage(tab.id, { action: 'getStats' });

            if (response && response.success) {
                displayStats(response.data);
            } else {
                statusText.innerHTML = '⚠️ 통계 데이터를 가져올 수 없습니다.<br><small>페이지를 새로고침 해주세요.</small>';
                statusBox.classList.remove('success');
                statusBox.classList.add('warning');
            }
        } catch (error) {
            console.error('Error getting stats:', error);
            statusText.innerHTML = '📊 통계 페이지를 새로고침 해주세요.<br><small>새로고침 후 다시 시도해주세요.</small>';
            statusBox.classList.remove('success');
            statusBox.classList.add('warning');
        }
    } else if (url.includes('blog.naver.com')) {
        // 블로그 페이지에 있지만 통계 페이지가 아님
        statusBox.classList.add('warning');
        statusText.innerHTML = '📝 블로그 페이지입니다.<br><small>통계를 보려면 아래 버튼을 클릭하세요.</small>';
    } else {
        // 네이버 블로그가 아님
        statusText.innerHTML = '🔍 네이버 블로그 통계를 확인하려면<br>블로그 관리 페이지로 이동해주세요.';
    }

    // 통계 페이지로 이동 버튼
    document.getElementById('go-stats-btn').addEventListener('click', () => {
        chrome.tabs.create({ url: 'https://admin.blog.naver.com/' });
    });

    // 내 블로그 관리 링크
    document.getElementById('link-blog').addEventListener('click', () => {
        chrome.tabs.create({ url: 'https://admin.blog.naver.com/' });
    });

    // 블로그 지수 분석기 링크
    document.getElementById('link-analyzer').addEventListener('click', () => {
        chrome.tabs.create({ url: 'https://blog-analyzer-kc8p.onrender.com/' });
    });

    // 내보내기 버튼
    exportBtn.addEventListener('click', async () => {
        const stats = await chrome.storage.local.get('blogStats');
        if (stats.blogStats) {
            const dataStr = JSON.stringify(stats.blogStats, null, 2);
            const blob = new Blob([dataStr], { type: 'application/json' });
            const url = URL.createObjectURL(blob);

            const a = document.createElement('a');
            a.href = url;
            a.download = `blog-stats-${new Date().toISOString().split('T')[0]}.json`;
            a.click();

            URL.revokeObjectURL(url);
        }
    });
});

// 통계 데이터 표시
function displayStats(data) {
    const statusBox = document.getElementById('status-box');
    const statusText = document.getElementById('status-text');
    const statsGrid = document.getElementById('stats-grid');
    const chartSection = document.getElementById('chart-section');
    const topPostsSection = document.getElementById('top-posts-section');
    const exportBtn = document.getElementById('export-btn');

    // 상태 업데이트
    statusBox.classList.remove('warning');
    statusBox.classList.add('success');
    statusText.innerHTML = '✅ 통계 데이터를 불러왔습니다!';

    // 통계 그리드 표시
    statsGrid.style.display = 'grid';

    // 방문자 수 표시
    document.getElementById('today-visitors').textContent = formatNumber(data.today || 0);
    document.getElementById('yesterday-visitors').textContent = formatNumber(data.yesterday || 0);
    document.getElementById('week-visitors').textContent = formatNumber(data.week || 0);
    document.getElementById('month-visitors').textContent = formatNumber(data.month || 0);

    // 변화율 계산
    if (data.today && data.yesterday) {
        const change = ((data.today - data.yesterday) / data.yesterday * 100).toFixed(1);
        const changeEl = document.getElementById('today-change');
        if (change > 0) {
            changeEl.textContent = `▲ ${change}%`;
            changeEl.className = 'change up';
        } else if (change < 0) {
            changeEl.textContent = `▼ ${Math.abs(change)}%`;
            changeEl.className = 'change down';
        }
    }

    // 차트 표시
    if (data.weeklyData && data.weeklyData.length > 0) {
        chartSection.style.display = 'block';
        const chartBars = document.getElementById('chart-bars');
        chartBars.innerHTML = '';

        const maxValue = Math.max(...data.weeklyData);
        data.weeklyData.forEach((value, index) => {
            const bar = document.createElement('div');
            bar.className = 'chart-bar';
            bar.style.height = `${(value / maxValue) * 70}px`;
            bar.title = `${value}명`;
            chartBars.appendChild(bar);
        });
    }

    // 인기 게시글 표시
    if (data.topPosts && data.topPosts.length > 0) {
        topPostsSection.style.display = 'block';
        const listEl = document.getElementById('top-posts-list');
        listEl.innerHTML = '';

        data.topPosts.slice(0, 5).forEach((post, index) => {
            const item = document.createElement('div');
            item.className = 'post-item';
            item.innerHTML = `
                <span class="post-rank">${index + 1}</span>
                <div class="post-info">
                    <div class="post-title">${post.title || '제목 없음'}</div>
                    <div class="post-views">조회수: ${formatNumber(post.views || 0)}</div>
                </div>
            `;
            listEl.appendChild(item);
        });
    }

    // 내보내기 버튼 표시
    exportBtn.style.display = 'block';

    // 데이터 저장
    chrome.storage.local.set({ blogStats: data });
}

// 숫자 포맷팅
function formatNumber(num) {
    if (num >= 10000) {
        return (num / 10000).toFixed(1) + '만';
    } else if (num >= 1000) {
        return (num / 1000).toFixed(1) + 'k';
    }
    return num.toLocaleString();
}
