"""
네이버 블로그 지수 분석기 - 백엔드 서버
=============================================
실제 네이버 블로그 데이터를 크롤링하여 분석합니다.

실행 방법:
1. pip install flask flask-cors requests beautifulsoup4 lxml
2. python blog_analyzer_server.py
3. http://localhost:5000 접속
"""

from flask import Flask, jsonify, request, send_from_directory, send_file
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import re
import os
import json
import time
import urllib.parse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# Supabase 연동 (REST API 직접 호출 방식)
SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://xmkhsiscudfsqejqtkaf.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')

def supabase_request(method, table, data=None, params=None):
    """Supabase REST API 직접 호출"""
    if not SUPABASE_KEY:
        return None

    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'
    }

    try:
        if method == 'GET':
            response = requests.get(url, headers=headers, params=params, timeout=10)
        elif method == 'POST':
            response = requests.post(url, headers=headers, json=data, timeout=10)

        if response.status_code in [200, 201]:
            return response.json()
        else:
            print(f"Supabase error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Supabase request error: {e}")
        return None

app = Flask(__name__, static_folder='static')
CORS(app)

# 네이버 블로그 크롤러
class NaverBlogCrawler:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': 'https://blog.naver.com/',
        }
    
    def crawl(self, blog_id, weekly_avg=0, weekly_count=0):
        """블로그 전체 정보 크롤링"""
        result = {
            'blog_id': blog_id,
            'blog_name': None,
            'blog_nickname': None,
            'profile_image': None,
            'neighbors': 0,
            'mutual_neighbors': 0,
            'total_posts': 0,
            'total_scraps': 0,
            'daily_visitors': 0,
            'total_visitors': 0,
            'recent_posts': [],
            'visitor_history': [],
            'blog_age_days': 0,
            'crawled_at': datetime.now().isoformat(),
            'error': None
        }
        
        try:
            # 1. 블로그 메인 페이지 크롤링
            self._crawl_main_page(blog_id, result)

            # 2. RSS 피드로 포스팅 정보 가져오기
            self._crawl_rss(blog_id, result)

            # 3. 프로필 페이지에서 추가 정보
            self._crawl_profile(blog_id, result)

            # 4. 방문자 통계 (위젯 공개 시)
            self._crawl_visitor_stats(blog_id, result)

            # 5. 모바일 페이지에서 추가 정보 (이웃, 방문자, 포스팅 수)
            self._crawl_mobile_page(blog_id, result)

            # 6. 지수 계산 (주간 평균 사용)
            result['index'] = self._calculate_index(result, weekly_avg=weekly_avg, weekly_count=weekly_count)

            # 7. 포스팅 지수 정보 (최근 15개 - 더보기 버튼으로 확장)
            if result.get('recent_posts'):
                result['posts_with_index'] = self._get_posts_with_index(
                    blog_id, result['recent_posts'], max_posts=15
                )

        except Exception as e:
            result['error'] = str(e)

        return result
    
    def _crawl_main_page(self, blog_id, result):
        """블로그 메인 페이지 크롤링"""
        try:
            # iframe 내부 페이지 직접 접근 (전체글 보기)
            url = f'https://blog.naver.com/PostList.naver?blogId={blog_id}&from=postList&categoryNo=0'
            response = requests.get(url, headers=self.headers, timeout=10)

            if response.status_code == 200:
                html = response.text
                soup = BeautifulSoup(html, 'html.parser')

                # 블로그명
                title_elem = soup.select_one('.nick, .blog_name, #nickNameArea')
                if title_elem:
                    result['blog_nickname'] = title_elem.get_text(strip=True)

                # 총 포스팅 수 추출: "112개의 글" 패턴
                post_count_match = re.search(r'(\d+)개의\s*글', html)
                if post_count_match:
                    result['total_posts'] = int(post_count_match.group(1))

                # 활동 정보 (이웃 수 등)
                activity_items = soup.select('.activity_item, .blog_info li')
                for item in activity_items:
                    text = item.get_text()

                    # 이웃 수
                    if '이웃' in text:
                        num = re.search(r'[\d,]+', text.replace(',', ''))
                        if num:
                            result['neighbors'] = int(num.group().replace(',', ''))

                    # 스크랩 수
                    if '스크랩' in text:
                        num = re.search(r'[\d,]+', text.replace(',', ''))
                        if num:
                            result['total_scraps'] = int(num.group().replace(',', ''))

        except Exception as e:
            print(f"Main page crawl error: {e}")
    
    def _crawl_rss(self, blog_id, result):
        """RSS 피드 크롤링 - 최근 30일 포스팅 수 분석 포함"""
        try:
            rss_url = f'https://rss.blog.naver.com/{blog_id}'
            response = requests.get(rss_url, headers=self.headers, timeout=10)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')

                # CDATA 제거 헬퍼 함수
                def clean_cdata(text):
                    if not text:
                        return ''
                    text = text.strip()
                    if text.startswith('<![CDATA[') and text.endswith(']]>'):
                        return text[9:-3].strip()
                    return text

                # 채널 정보
                channel = soup.find('channel')
                if channel:
                    title = channel.find('title')
                    if title:
                        result['blog_name'] = clean_cdata(title.text.strip() if title.text else '')

                    # 프로필 이미지
                    image = channel.find('image')
                    if image:
                        url = image.find('url')
                        if url:
                            result['profile_image'] = clean_cdata(url.text.strip() if url.text else '')

                # 포스팅 목록
                items = soup.find_all('item')
                if result.get('total_posts', 0) == 0:
                    result['total_posts'] = len(items)

                # 최근 30일 포스팅 수 계산
                recent_30days_count = 0
                now = datetime.now()
                thirty_days_ago = now - timedelta(days=30)

                for item in items:
                    # HTML 파서가 태그명을 소문자로 변환하므로 둘 다 시도
                    pub_date = item.find('pubDate') or item.find('pubdate')
                    if pub_date:
                        try:
                            # RSS 날짜 형식: "Wed, 31 Dec 2025 11:05:39 +0900"
                            date_str = pub_date.text.strip()
                            post_date = datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S %z')
                            post_date = post_date.replace(tzinfo=None)  # timezone 제거
                            if post_date >= thirty_days_ago:
                                recent_30days_count += 1
                        except Exception as e:
                            print(f"Date parsing error: {e}, date_str: {date_str}")

                result['recent_30days_posts'] = recent_30days_count

                # CDATA 제거 함수
                def strip_cdata(text):
                    if not text:
                        return ''
                    text = text.strip()
                    if text.startswith('<![CDATA[') and text.endswith(']]>'):
                        return text[9:-3].strip()
                    return text

                # 최근 포스트 50개 저장 (RSS 전체)
                for item in items[:50]:
                    post = {}

                    title = item.find('title')
                    if title:
                        post['title'] = strip_cdata(title.text.strip() if title.text else '')

                    link = item.find('link')
                    if link:
                        link_text = link.text.strip() if link.text else ''
                        # link 태그 다음 텍스트 노드도 확인
                        if not link_text and link.next_sibling:
                            link_text = str(link.next_sibling).strip()
                        post['link'] = strip_cdata(link_text)

                    pub_date = item.find('pubDate') or item.find('pubdate')
                    if pub_date:
                        post['date'] = pub_date.text.strip() if pub_date.text else ''

                    description = item.find('description')
                    if description:
                        desc_text = strip_cdata(description.text.strip() if description.text else '')
                        desc_soup = BeautifulSoup(desc_text, 'html.parser')
                        post['description'] = desc_soup.get_text()[:100] + '...'

                    result['recent_posts'].append(post)

        except Exception as e:
            print(f"RSS crawl error: {e}")

    def _get_post_details(self, blog_id, post_url):
        """개별 포스팅의 공감/댓글/이미지 수 가져오기 - 개선된 버전"""
        try:
            # URL에서 logNo 추출 - 더 정확한 패턴 사용
            log_no_match = re.search(r'/(\d{10,})', post_url) or re.search(r'logNo=(\d+)', post_url)
            if not log_no_match:
                # 기본값 반환 (데이터 누락 방지)
                return {'likes': 0, 'comments': 0, 'images': 0, 'char_count': 0, 'word_count': 0, 'subheading_count': 0, 'link_count': 0, 'has_video': False, 'image_seo': {}}

            log_no = log_no_match.group(1)

            # URL에서 실제 blogId 추출
            url_blog_id_match = re.search(r'blog\.naver\.com/([a-zA-Z0-9_-]+)', post_url)
            actual_blog_id = url_blog_id_match.group(1) if url_blog_id_match else blog_id

            # 모바일 페이지로 접근 (더 간단한 구조)
            mobile_headers = {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
            }
            mobile_url = f'https://m.blog.naver.com/{actual_blog_id}/{log_no}'
            response = requests.get(mobile_url, headers=mobile_headers, timeout=10)

            if response.status_code != 200:
                return {'likes': 0, 'comments': 0, 'images': 0, 'char_count': 0, 'word_count': 0, 'subheading_count': 0, 'link_count': 0, 'has_video': False, 'image_seo': {}}

            html = response.text
            soup = BeautifulSoup(html, 'html.parser')

            # ===== 공감 수 수집 (개선) =====
            likes = 0
            # 1순위: JSON 데이터에서 추출
            like_patterns = [
                r'"sympathyCount"\s*:\s*(\d+)',
                r'sympathyCount["\s:]+(\d+)',
                r'"likeCount"\s*:\s*(\d+)',
                r'"sympathy_count"\s*:\s*(\d+)',
            ]
            for pattern in like_patterns:
                like_match = re.search(pattern, html)
                if like_match:
                    likes = int(like_match.group(1))
                    break

            # 2순위: DOM 요소에서 추출
            if likes == 0:
                like_selectors = [
                    '.u_cnt._count',
                    '.sympathy_cnt',
                    '.like_cnt',
                    '.post_sympathy_count',
                    '.u_likeit_list_count',
                    '[class*="sympathy"] [class*="count"]',
                    '[class*="like"] [class*="count"]',
                ]
                for selector in like_selectors:
                    like_elem = soup.select_one(selector)
                    if like_elem:
                        num = re.search(r'\d+', like_elem.get_text())
                        if num:
                            likes = int(num.group())
                            break

            # ===== 댓글 수 수집 (개선) =====
            comments = 0
            # 1순위: JSON 데이터에서 추출
            comment_patterns = [
                r'"commentCount"\s*:\s*(\d+)',
                r'commentCount["\s:]+(\d+)',
                r'"comment_count"\s*:\s*(\d+)',
                r'"replyCount"\s*:\s*(\d+)',
            ]
            for pattern in comment_patterns:
                comment_match = re.search(pattern, html)
                if comment_match:
                    comments = int(comment_match.group(1))
                    break

            # 2순위: DOM 요소에서 추출
            if comments == 0:
                comment_selectors = [
                    '.comment_count',
                    '.cmt_cnt',
                    '.post_comment_count',
                    '[class*="comment"] [class*="count"]',
                    '[class*="reply"] [class*="count"]',
                ]
                for selector in comment_selectors:
                    comment_elem = soup.select_one(selector)
                    if comment_elem:
                        num = re.search(r'\d+', comment_elem.get_text())
                        if num:
                            comments = int(num.group())
                            break

            # ===== 이미지 수 수집 (개선) =====
            unique_image_hashes = set()

            # 1단계: 모든 pstatic.net/postfiles/blogfiles 이미지 URL 찾기
            image_url_patterns = [
                r'https?:[^\"\s<>\']*pstatic\.net[^\"\s<>\']*',
                r'https?:[^\"\s<>\']*postfiles[^\"\s<>\']*',
                r'https?:[^\"\s<>\']*blogfiles[^\"\s<>\']*',
            ]

            all_image_urls = []
            for pattern in image_url_patterns:
                all_image_urls.extend(re.findall(pattern, html))

            for url in all_image_urls:
                # 이스케이프 문자 정리
                clean = url.replace('\\/', '/').replace('\\', '/').replace('\\"', '')

                # 아이콘, 정적 리소스, 프로필 제외
                exclude_patterns = ['static/blog', 'static.blog', 'blogpfthumb', 'profile', 'icon', 'btn_', 'bg_']
                if any(exc in clean.lower() for exc in exclude_patterns):
                    continue

                # 이미지 확장자 체크 (대소문자 무관)
                if not any(ext in clean.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']):
                    continue

                # 이미지 해시 추출 - 여러 패턴 지원
                hash_patterns = [
                    r'/([A-Za-z0-9_-]{10,})/([A-Za-z0-9_.-]+)\.(?:jpg|jpeg|png|gif|webp|bmp)',
                    r'postfiles\d*/([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+)',
                    r'blogfiles\d*/([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+)',
                ]
                for hash_pattern in hash_patterns:
                    hash_match = re.search(hash_pattern, clean, re.IGNORECASE)
                    if hash_match:
                        unique_key = f"{hash_match.group(1)}_{hash_match.group(2)[:20]}"
                        unique_image_hashes.add(unique_key)
                        break

            images = len(unique_image_hashes)

            # 2단계: img 태그에서 직접 검색 (백업)
            if images == 0:
                img_tags = soup.select('img')
                for img in img_tags:
                    # 다양한 속성에서 이미지 URL 추출
                    src = img.get('src', '') or img.get('data-lazy-src', '') or img.get('data-src', '') or img.get('data-original', '') or ''

                    if not src:
                        continue

                    # 본문 이미지만 카운트 (프로필, 아이콘 제외)
                    if any(exc in src.lower() for exc in ['blogpfthumb', 'profile', 'icon', 'btn_', 'bg_']):
                        continue

                    if 'blogfiles' in src or 'postfiles' in src or 'pstatic.net' in src:
                        hash_match = re.search(r'/([A-Za-z0-9_-]{10,})/([A-Za-z0-9_.-]+)', src)
                        if hash_match:
                            unique_image_hashes.add(f"{hash_match.group(1)}_{hash_match.group(2)[:20]}")
                images = len(unique_image_hashes)

            # 3단계: se-image 컴포넌트에서 직접 카운트 (최종 백업)
            if images == 0:
                se_images = soup.select('.se-image-resource, .se-component-image img, .se_mediaImage')
                images = len(se_images)

            # 본문 분석 추가
            content_analysis = self._analyze_content(html, soup)

            # 이미지 SEO 분석
            image_seo = self._analyze_image_seo(html, soup)

            return {
                'likes': likes,
                'comments': comments,
                'images': images,
                'char_count': content_analysis.get('char_count', 0),
                'word_count': content_analysis.get('word_count', 0),
                'subheading_count': content_analysis.get('subheading_count', 0),
                'link_count': content_analysis.get('link_count', 0),
                'has_video': content_analysis.get('has_video', False),
                'image_seo': image_seo
            }

        except Exception as e:
            print(f"Post detail crawl error: {e}")
            return {'likes': 0, 'comments': 0, 'images': 0, 'char_count': 0, 'word_count': 0, 'subheading_count': 0, 'link_count': 0, 'has_video': False, 'image_seo': {}}

    def _analyze_content(self, html, soup):
        """본문 콘텐츠 분석 - 개선된 버전"""
        try:
            content_text = ''

            # 1단계: 스마트에디터 ONE (SE ONE) 본문 추출 - 최신 버전
            se_one_selectors = [
                '.se-main-container .se-text-paragraph',
                '.se-main-container .se-text',
                '.se-component-content',
                '.se-module-text',
            ]
            for selector in se_one_selectors:
                elements = soup.select(selector)
                for elem in elements:
                    text = elem.get_text(strip=True)
                    if text and len(text) > 5:  # 너무 짧은 텍스트 제외
                        content_text += text + ' '

            # 2단계: 구버전 스마트에디터 (SE2, SE3)
            if len(content_text.strip()) < 100:
                legacy_selectors = [
                    '.se-text-paragraph',
                    '.se_textarea',
                    '.post_ct',
                    '.__se_module_data',
                    '.se_doc_viewer',
                    '#postViewArea',
                    '.post-view',
                    '.se_component_wrap',
                ]
                for selector in legacy_selectors:
                    elements = soup.select(selector)
                    for elem in elements:
                        text = elem.get_text(strip=True)
                        if text and len(text) > 5:
                            content_text += text + ' '

            # 3단계: JSON 데이터에서 추출 (백업)
            if len(content_text.strip()) < 100:
                # contentText 패턴 - 더 넓은 범위로 검색
                content_patterns = [
                    r'"contentText"\s*:\s*"((?:[^"\\]|\\.)*)"|\'contentText\'\s*:\s*\'((?:[^\'\\]|\\.)*)\'',
                    r'"plainText"\s*:\s*"((?:[^"\\]|\\.)*)"|\'plainText\'\s*:\s*\'((?:[^\'\\]|\\.)*)\'',
                    r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"|\'content\'\s*:\s*\'((?:[^\'\\]|\\.)*)\'',
                ]
                for pattern in content_patterns:
                    matches = re.findall(pattern, html, re.DOTALL)
                    for match in matches:
                        text = match[0] if match[0] else match[1] if len(match) > 1 else ''
                        if text and len(text) > 100:
                            # 이스케이프 문자 처리
                            text = text.replace('\\n', ' ').replace('\\t', ' ').replace('\\r', '')
                            text = re.sub(r'\\u[0-9a-fA-F]{4}', '', text)  # 유니코드 이스케이프 제거
                            content_text = text
                            break
                    if len(content_text.strip()) >= 100:
                        break

            # 4단계: HTML 태그 제거 후 본문 영역에서 직접 추출 (최후 수단)
            if len(content_text.strip()) < 100:
                # 본문 컨테이너 찾기
                content_containers = soup.select('.post_ct, #content-area, .se_component_wrap, article')
                for container in content_containers:
                    # 스크립트, 스타일 태그 제거
                    for script in container.select('script, style, noscript'):
                        script.decompose()
                    text = container.get_text(separator=' ', strip=True)
                    if len(text) > len(content_text):
                        content_text = text

            # HTML 태그 잔여물 정리
            content_text = re.sub(r'<[^>]+>', '', content_text)
            content_text = re.sub(r'\s+', ' ', content_text).strip()

            # 글자 수 (공백 제외) - 한글, 영문, 숫자만 카운트
            clean_text = re.sub(r'\s', '', content_text)
            char_count = len(clean_text)

            # 최소값 보장 (본문이 있는데 0으로 나오는 경우 방지)
            if char_count == 0 and len(content_text) > 0:
                char_count = len(content_text)

            # 단어 수 (한글 기준으로 어절 수)
            words = content_text.split()
            word_count = len(words)

            # 소제목 수 (h2, h3 또는 볼드/강조 텍스트)
            subheading_count = 0
            subheading_patterns = [
                r'<h[23][^>]*>',
                r'class="[^"]*se-section-title[^"]*"',
                r'class="[^"]*se-text-paragraph-bold[^"]*"',
                r'class="[^"]*se_textarea[^"]*"[^>]*style="[^"]*font-weight:\s*bold',
                r'<strong[^>]*class="[^"]*se-[^"]*"',
            ]
            for pattern in subheading_patterns:
                subheading_count += len(re.findall(pattern, html, re.IGNORECASE))

            # 링크 수 - 외부 링크만 카운트 (네이버 내부 링크 제외 옵션)
            all_links = soup.select('a[href*="http"]')
            link_count = len([link for link in all_links if link.get('href')])

            # 동영상 포함 여부 - 더 정확한 판단
            video_selectors = [
                '.se-video',
                '.se_mediaArea video',
                'iframe[src*="youtube"]',
                'iframe[src*="naver"]',
                'iframe[src*="vimeo"]',
                '.se-oglink-video',
                'video',
            ]
            has_video = any(soup.select(selector) for selector in video_selectors)
            if not has_video:
                # HTML 내 비디오 관련 키워드 검색 (더 정확하게)
                has_video = bool(re.search(r'(youtube\.com/embed|player\.vimeo|tv\.naver\.com|video\.naver\.com)', html, re.IGNORECASE))

            return {
                'char_count': char_count,
                'word_count': word_count,
                'subheading_count': subheading_count,
                'link_count': link_count,
                'has_video': has_video
            }

        except Exception as e:
            print(f"Content analysis error: {e}")
            return {'char_count': 0, 'word_count': 0, 'subheading_count': 0, 'link_count': 0, 'has_video': False}

    def _analyze_image_seo(self, html, soup):
        """이미지 SEO 분석 (ALT 태그, 파일명 등)"""
        try:
            result = {
                'total_images': 0,
                'with_alt': 0,
                'without_alt': 0,
                'alt_quality': 'unknown',
                'has_descriptive_filename': False,
                'recommendations': []
            }

            # 모든 이미지 태그 찾기
            img_tags = soup.select('img')
            content_images = []

            for img in img_tags:
                src = img.get('src', '') or img.get('data-lazy-src', '') or img.get('data-src', '') or ''

                # 본문 이미지만 (프로필, 아이콘 제외)
                if ('blogfiles' in src or 'postfiles' in src or 'pstatic.net' in src) and 'blogpfthumb' not in src:
                    content_images.append(img)

            result['total_images'] = len(content_images)

            # ALT 태그 분석
            for img in content_images:
                alt = img.get('alt', '').strip()
                if alt and len(alt) > 2:
                    result['with_alt'] += 1
                else:
                    result['without_alt'] += 1

            # ALT 품질 평가
            if result['total_images'] == 0:
                result['alt_quality'] = 'no_images'
            elif result['with_alt'] == result['total_images']:
                result['alt_quality'] = 'excellent'
            elif result['with_alt'] >= result['total_images'] * 0.7:
                result['alt_quality'] = 'good'
            elif result['with_alt'] >= result['total_images'] * 0.3:
                result['alt_quality'] = 'average'
            else:
                result['alt_quality'] = 'poor'

            # 파일명 분석 (한글 또는 설명적 파일명 체크)
            for img in content_images:
                src = img.get('src', '') or img.get('data-lazy-src', '') or ''
                # 한글이 포함되어 있거나 의미있는 파일명인 경우
                if re.search(r'[가-힣]', src) or re.search(r'[a-zA-Z]{5,}', src.split('/')[-1]):
                    result['has_descriptive_filename'] = True
                    break

            # SEO 권장사항 생성
            if result['without_alt'] > 0:
                result['recommendations'].append(f"이미지 {result['without_alt']}개에 ALT 태그 추가 권장")
            if result['total_images'] == 0:
                result['recommendations'].append("본문에 이미지를 추가하면 SEO에 도움됩니다")
            elif result['total_images'] < 3:
                result['recommendations'].append("이미지를 3개 이상 추가하면 좋습니다")
            if result['total_images'] > 0 and result['alt_quality'] in ['poor', 'average']:
                result['recommendations'].append("이미지 ALT 태그에 키워드를 포함하세요")

            return result

        except Exception as e:
            print(f"Image SEO analysis error: {e}")
            return {'total_images': 0, 'with_alt': 0, 'without_alt': 0, 'alt_quality': 'unknown', 'recommendations': []}

    def _extract_keyword(self, post_title):
        """제목에서 검색용 키워드 추출"""
        if not post_title:
            return ''

        # 1. 대괄호 [] 안 내용 추출
        bracket_match = re.search(r'\[([^\]]+)\]', post_title)
        if bracket_match:
            return bracket_match.group(1).strip()

        # 2. 대괄호 없으면 제목에서 불용어 제거 후 앞 4단어
        # 불용어 제거 (조사, 접속사 등)
        stopwords = ['의', '가', '이', '은', '는', '을', '를', '에', '와', '과', '도', '로', '으로',
                     '에서', '까지', '부터', '만', '보다', '처럼', '같이', '대한', '관한', '위한',
                     '그리고', '하지만', '그러나', '또한', '및', '등', '것', '수', '있는', '없는',
                     '하는', '되는', '된', '한', '할', '함', '있다', '없다', '하다']

        # 특수문자 제거하고 단어 분리
        clean_title = re.sub(r'[^\w\s]', ' ', post_title)
        words = clean_title.split()

        # 불용어 제거 및 1글자 제거
        keywords = [w for w in words if w not in stopwords and len(w) > 1]

        # 앞 4단어 반환
        return ' '.join(keywords[:4])

    def _check_search_exposure(self, blog_id, post_title, post_url):
        """네이버 검색에서 포스팅 노출 여부 확인 (키워드 기반) - 개선된 버전"""
        try:
            # URL에서 실제 블로그 ID와 logNo 추출
            url_blog_id_match = re.search(r'blog\.naver\.com/([a-zA-Z0-9_-]+)', post_url)
            actual_blog_id = url_blog_id_match.group(1) if url_blog_id_match else blog_id

            log_no_match = re.search(r'/(\d{10,})', post_url) or re.search(r'logNo=(\d+)', post_url)
            log_no = log_no_match.group(1) if log_no_match else ''

            # 제목에서 키워드 추출
            keyword = self._extract_keyword(post_title)
            if not keyword:
                return 'unknown', ''

            # 키워드로 네이버 블로그 검색
            search_query = urllib.parse.quote(keyword)
            search_url = f'https://search.naver.com/search.naver?where=blog&query={search_query}'

            response = requests.get(search_url, headers=self.headers, timeout=10)

            if response.status_code != 200:
                return 'unknown', keyword

            html = response.text
            soup = BeautifulSoup(html, 'html.parser')

            # ===== 개선된 노출 판단 로직 =====
            # 검색 결과 항목들을 개별적으로 확인
            search_items = soup.select('.api_txt_lines, .title_link, .total_tit, .sh_blog_title')

            # 1순위: 정확한 포스팅 URL 매칭 (blog_id + log_no)
            exact_match_patterns = [
                f'{actual_blog_id}/{log_no}',
                f'blogId={actual_blog_id}.*logNo={log_no}',
                f'{actual_blog_id}.*{log_no}',
            ]
            for pattern in exact_match_patterns:
                if re.search(pattern, html, re.IGNORECASE):
                    return 'indexed', keyword  # 정확한 포스팅이 노출됨

            # 2순위: 검색 결과에서 링크 직접 확인
            all_links = soup.select('a[href*="blog.naver.com"]')
            for link in all_links:
                href = link.get('href', '')
                if actual_blog_id in href and log_no in href:
                    return 'indexed', keyword

            # 3순위: 제목 유사도 확인 (같은 블로그의 다른 글이 노출된 경우와 구분)
            # 실제 포스팅 제목의 핵심 단어가 검색결과 제목에 포함되어 있는지 확인
            title_keywords = set(re.findall(r'[가-힣a-zA-Z0-9]{2,}', post_title))
            if len(title_keywords) > 0:
                for item in search_items:
                    item_text = item.get_text(strip=True)
                    # 검색결과 항목에서 블로그ID 확인
                    parent_html = str(item.parent) if item.parent else ''
                    if actual_blog_id in parent_html:
                        # 제목 키워드 매칭 (50% 이상 일치시 해당 포스팅으로 판단)
                        item_keywords = set(re.findall(r'[가-힣a-zA-Z0-9]{2,}', item_text))
                        if len(title_keywords) > 0:
                            match_ratio = len(title_keywords & item_keywords) / len(title_keywords)
                            if match_ratio >= 0.5:
                                return 'indexed', keyword

            # 4순위: 블로그 ID만 검색결과에 있는 경우
            # 다른 포스팅이 노출된 것일 수 있으므로 'pending'으로 표시
            if actual_blog_id in html:
                return 'pending', keyword  # 블로그는 검색되나 해당 글인지 불확실

            # 검색결과에 블로그 ID 자체가 없음
            return 'missing', keyword

        except Exception as e:
            print(f"Search check error: {e}")
            return 'unknown', ''

    def _get_posts_with_index(self, blog_id, posts, max_posts=5):
        """포스팅 목록에 지수 정보 추가 (병렬 처리) - 개선된 버전"""
        enriched_posts = []

        # 최대 5개 상세 분석 (메모리 최적화)
        posts_to_analyze = posts[:max_posts]

        def analyze_post(post):
            """개별 포스팅 분석 - 에러 발생시 기본값 반환"""
            post_url = post.get('link', '')
            post_title = post.get('title', '')

            # 기본값 설정 (데이터 누락 방지)
            default_result = {
                **post,
                'likes': 0,
                'comments': 0,
                'images': 0,
                'exposure': 'unknown',
                'keyword': '',
                'char_count': 0,
                'word_count': 0,
                'subheading_count': 0,
                'link_count': 0,
                'has_video': False,
                'image_seo': {}
            }

            try:
                # 상세 정보 가져오기
                details = self._get_post_details(blog_id, post_url)

                # 검색 노출 여부 확인 (요청 간격 두기)
                time.sleep(0.3)
                exposure, keyword = self._check_search_exposure(blog_id, post_title, post_url)

                return {
                    **post,
                    'likes': details.get('likes', 0),
                    'comments': details.get('comments', 0),
                    'images': details.get('images', 0),
                    'exposure': exposure if exposure else 'unknown',
                    'keyword': keyword if keyword else '',
                    # 본문 분석 데이터 - 기본값 보장
                    'char_count': details.get('char_count', 0),
                    'word_count': details.get('word_count', 0),
                    'subheading_count': details.get('subheading_count', 0),
                    'link_count': details.get('link_count', 0),
                    'has_video': details.get('has_video', False),
                    'image_seo': details.get('image_seo', {})
                }
            except Exception as e:
                print(f"Individual post analysis error for {post_url}: {e}")
                return default_result

        # 병렬 처리 (최대 2개 동시 - 메모리 최적화)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {executor.submit(analyze_post, post): post for post in posts_to_analyze}
            for future in as_completed(futures):
                try:
                    result = future.result()
                    enriched_posts.append(result)
                except Exception as e:
                    # 병렬 처리 실패시에도 기본 데이터로 추가
                    original_post = futures[future]
                    print(f"Post analysis future error: {e}")
                    enriched_posts.append({
                        **original_post,
                        'likes': 0,
                        'comments': 0,
                        'images': 0,
                        'exposure': 'unknown',
                        'keyword': '',
                        'char_count': 0,
                        'word_count': 0,
                        'subheading_count': 0,
                        'link_count': 0,
                        'has_video': False,
                        'image_seo': {}
                    })

        # 원래 순서대로 정렬 (제목 기준)
        title_order = {post.get('title', ''): i for i, post in enumerate(posts_to_analyze)}
        enriched_posts.sort(key=lambda x: title_order.get(x.get('title', ''), 999))

        return enriched_posts

    def _crawl_profile(self, blog_id, result):
        """프로필 페이지 크롤링"""
        try:
            profile_url = f'https://blog.naver.com/profile/intro.naver?blogId={blog_id}'
            response = requests.get(profile_url, headers=self.headers, timeout=10)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')

                # 이웃 수
                neighbor_elem = soup.select_one('.neighbor_count, .buddy_count')
                if neighbor_elem:
                    num = re.search(r'[\d,]+', neighbor_elem.get_text())
                    if num:
                        result['neighbors'] = int(num.group().replace(',', ''))

                # 블로그 시작일
                since_elem = soup.select_one('.since, .blog_since')
                if since_elem:
                    date_match = re.search(r'(\d{4})\.(\d{1,2})\.(\d{1,2})', since_elem.get_text())
                    if date_match:
                        start_date = datetime(int(date_match.group(1)),
                                             int(date_match.group(2)),
                                             int(date_match.group(3)))
                        result['blog_age_days'] = (datetime.now() - start_date).days

        except Exception as e:
            print(f"Profile crawl error: {e}")

    def _crawl_mobile_page(self, blog_id, result):
        """모바일 페이지 크롤링 - 이웃 수, 방문자 수, 프로필 이미지 가져오기"""
        try:
            mobile_headers = {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'ko-KR,ko;q=0.9',
            }

            url = f'https://m.blog.naver.com/{blog_id}'
            response = requests.get(url, headers=mobile_headers, timeout=10)

            if response.status_code == 200:
                html = response.text

                # 프로필 이미지 추출 (여러 패턴 시도)
                if not result.get('profile_image'):
                    # 패턴 1: profileImageUrl JSON
                    profile_match = re.search(r'"profileImageUrl"\s*:\s*"([^"]+)"', html)
                    if profile_match:
                        result['profile_image'] = profile_match.group(1).replace('\\/', '/')

                    # 패턴 2: 프로필 이미지 URL 직접 찾기
                    if not result.get('profile_image'):
                        profile_match = re.search(r'(https://[^"\']*(?:blogpfp|profile)[^"\']*\.(?:jpg|png|gif))', html, re.IGNORECASE)
                        if profile_match:
                            result['profile_image'] = profile_match.group(1)

                # 이웃 수 추출: "25명의 이웃" 패턴
                buddy_match = re.search(r'(\d+)명의\s*이웃', html)
                if buddy_match and result.get('neighbors', 0) == 0:
                    result['neighbors'] = int(buddy_match.group(1))

                # 방문자 수 추출: "오늘 X 어제 Y 전체 Z" 패턴
                # 먼저 어제 방문자를 포함한 패턴 시도
                visitor_full_match = re.search(r'오늘\s*(\d+).*?어제\s*(\d+).*?전체\s*([\d,]+)', html, re.DOTALL)
                if visitor_full_match:
                    if result.get('daily_visitors', 0) == 0:
                        result['daily_visitors'] = int(visitor_full_match.group(1))
                    if result.get('yesterday_visitors', 0) == 0:
                        result['yesterday_visitors'] = int(visitor_full_match.group(2))
                    if result.get('total_visitors', 0) == 0:
                        result['total_visitors'] = int(visitor_full_match.group(3).replace(',', ''))
                else:
                    # 어제가 없는 경우 기존 패턴 사용
                    visitor_match = re.search(r'오늘\s*(\d+).*?전체\s*([\d,]+)', html, re.DOTALL)
                    if visitor_match:
                        if result.get('daily_visitors', 0) == 0:
                            result['daily_visitors'] = int(visitor_match.group(1))
                        if result.get('total_visitors', 0) == 0:
                            result['total_visitors'] = int(visitor_match.group(2).replace(',', ''))

                # 어제 방문자만 따로 추출 시도
                if result.get('yesterday_visitors', 0) == 0:
                    yesterday_match = re.search(r'어제\s*(\d[\d,]*)', html)
                    if yesterday_match:
                        result['yesterday_visitors'] = int(yesterday_match.group(1).replace(',', ''))

                # 총 포스팅 수 추출 (JSON 데이터에서)
                post_count_match = re.search(r'"totalCount"\s*:\s*(\d+)', html)
                if post_count_match:
                    total_posts = int(post_count_match.group(1))
                    if total_posts > result.get('total_posts', 0):
                        result['total_posts'] = total_posts

        except Exception as e:
            print(f"Mobile page crawl error: {e}")
    
    def _analyze_keywords(self, recent_posts):
        """
        포스트 제목에서 키워드 분석하여 주제 일관성 점수 계산
        - 반복 키워드가 많으면 주제 일관성 높음
        - 다양한 키워드면 주제 분산
        """
        if not recent_posts:
            return 10  # 기본 점수

        # 제목에서 키워드 추출
        all_words = []
        for post in recent_posts:
            title = post.get('title', '')
            # 한글, 영문 단어만 추출 (2글자 이상)
            words = re.findall(r'[가-힣]{2,}|[a-zA-Z]{3,}', title)
            all_words.extend(words)

        if not all_words:
            return 10

        # 불용어 제거
        stopwords = {'그리고', '하지만', '그래서', '또한', '하는', '있는', '없는', '되는',
                     '이런', '저런', '어떤', '모든', '같은', '다른', '우리', '나의',
                     'the', 'and', 'for', 'with', 'this', 'that', 'from', 'are'}
        words = [w for w in all_words if w.lower() not in stopwords]

        if not words:
            return 10

        # 키워드 빈도 분석
        word_count = {}
        for word in words:
            word_count[word] = word_count.get(word, 0) + 1

        # 상위 키워드 집중도 계산
        total_words = len(words)
        sorted_words = sorted(word_count.items(), key=lambda x: x[1], reverse=True)
        top_5_count = sum(count for _, count in sorted_words[:5])

        # 집중도: 상위 5개 키워드가 전체의 몇 %인지
        concentration = (top_5_count / total_words) * 100 if total_words > 0 else 0

        # 집중도에 따른 점수 (30~70% 집중도가 최적)
        if 30 <= concentration <= 70:
            keyword_score = 20  # 최적
        elif 20 <= concentration < 30 or 70 < concentration <= 80:
            keyword_score = 15  # 양호
        elif 10 <= concentration < 20 or 80 < concentration <= 90:
            keyword_score = 10  # 보통
        else:
            keyword_score = 5  # 너무 분산되거나 너무 집중됨

        return keyword_score

    def _crawl_visitor_stats(self, blog_id, result):
        """방문자 통계 크롤링 (위젯 공개 시)"""
        try:
            # 방문자 카운터 API
            visitor_url = f'https://blog.naver.com/NVisitorg498Ajax.naver?blogId={blog_id}'
            response = requests.get(visitor_url, headers=self.headers, timeout=10)

            if response.status_code == 200:
                # 오늘 방문자
                today_match = re.search(r'today["\']?\s*:\s*["\']?(\d+)', response.text)
                if today_match:
                    result['daily_visitors'] = int(today_match.group(1))

                # 어제 방문자 (yesterday 또는 yester)
                yesterday_match = re.search(r'(?:yesterday|yester)["\']?\s*:\s*["\']?(\d+)', response.text, re.IGNORECASE)
                if yesterday_match:
                    result['yesterday_visitors'] = int(yesterday_match.group(1))

                # 전체 방문자
                total_match = re.search(r'total["\']?\s*:\s*["\']?(\d+)', response.text)
                if total_match:
                    result['total_visitors'] = int(total_match.group(1))

            # 방법 2: 블로그 메인 페이지에서 어제 방문자 크롤링
            if result.get('yesterday_visitors', 0) == 0:
                try:
                    blog_url = f'https://blog.naver.com/prologue/PrologueList.naver?blogId={blog_id}'
                    resp = requests.get(blog_url, headers=self.headers, timeout=10)
                    if resp.status_code == 200:
                        # 어제 방문자 패턴 찾기
                        yester_match = re.search(r'어제\s*(?:방문자?)?\s*[:：]?\s*(\d[\d,]*)', resp.text)
                        if yester_match:
                            result['yesterday_visitors'] = int(yester_match.group(1).replace(',', ''))
                except:
                    pass

        except Exception as e:
            print(f"Visitor stats crawl error: {e}")
    
    def _calculate_index(self, data, weekly_avg=0, weekly_count=0):
        """
        블로그 지수 계산 - 노출 중심
        핵심: 노출 많음 → 방문자 많음 → 지수 높음

        우선순위:
        1. 주간 평균 (3일 이상 데이터) - 가장 정확
        2. 어제 방문자 - 자정 이후 보정용
        3. 전체 방문자 기반 추정 - 최후 수단
        """
        import math
        from datetime import datetime

        daily_visitors = data.get('daily_visitors', 0)
        yesterday_visitors = data.get('yesterday_visitors', 0)
        total_visitors = data.get('total_visitors', 0)
        neighbors = data.get('neighbors', 0)
        total_posts = data.get('total_posts', 0)
        recent_posts = data.get('recent_30days_posts', 0)
        blog_age_days = data.get('blog_age_days', 1)

        current_hour = datetime.now().hour
        visitor_source = 'today'  # 어떤 데이터를 사용했는지 추적

        # ★ 최우선: 주간 평균 사용 (3일 이상 데이터가 있을 때)
        if weekly_avg > 0 and weekly_count >= 3:
            daily_visitors = weekly_avg
            visitor_source = f'weekly_avg_{weekly_count}days'
        else:
            # 주간 평균이 없을 때만 보정 로직 사용

            # 1순위: 어제 방문자 사용
            if daily_visitors < 10 and yesterday_visitors > 0:
                if current_hour < 6:
                    daily_visitors = yesterday_visitors
                    visitor_source = 'yesterday_full'
                elif current_hour < 12:
                    daily_visitors = max(daily_visitors, int(yesterday_visitors * 0.5))
                    visitor_source = 'yesterday_50pct'
                else:
                    daily_visitors = max(daily_visitors, int(yesterday_visitors * 0.3))
                    visitor_source = 'yesterday_30pct'

            # 2순위: 전체 방문자 기반 추정
            if daily_visitors < 10 and total_visitors > 0:
                if blog_age_days > 0:
                    estimated_daily = total_visitors / max(blog_age_days, 1)
                    daily_visitors = max(daily_visitors, int(estimated_daily * 0.7))
                    visitor_source = 'total_estimated'
                else:
                    # 전체 방문자 구간별 최소 보정
                    if total_visitors >= 100000:
                        daily_visitors = max(daily_visitors, 150)
                    elif total_visitors >= 50000:
                        daily_visitors = max(daily_visitors, 100)
                    elif total_visitors >= 20000:
                        daily_visitors = max(daily_visitors, 60)
                    elif total_visitors >= 10000:
                        daily_visitors = max(daily_visitors, 40)
                    elif total_visitors >= 5000:
                        daily_visitors = max(daily_visitors, 25)
                    elif total_visitors >= 2000:
                        daily_visitors = max(daily_visitors, 15)
                    elif total_visitors >= 1000:
                        daily_visitors = max(daily_visitors, 10)
                    elif total_visitors >= 500:
                        daily_visitors = max(daily_visitors, 8)
                    visitor_source = 'total_tier'

        # 3순위: 이웃 수 기반 최소 보정
        if daily_visitors < 10:
            if neighbors >= 500:
                daily_visitors = max(daily_visitors, 50)
            elif neighbors >= 100:
                daily_visitors = max(daily_visitors, 20)
            elif neighbors >= 30:
                daily_visitors = max(daily_visitors, 10)

        # 1. 노출 지수 (100점 만점) - 핵심 지표
        # 일일 방문자가 노출의 직접적인 결과
        if daily_visitors >= 1000:
            exposure_score = 95 + min(5, (daily_visitors - 1000) / 1000)
        elif daily_visitors >= 500:
            exposure_score = 85 + (daily_visitors - 500) / 50
        elif daily_visitors >= 200:
            exposure_score = 70 + (daily_visitors - 200) / 20
        elif daily_visitors >= 100:
            exposure_score = 55 + (daily_visitors - 100) / 6.67
        elif daily_visitors >= 50:
            exposure_score = 40 + (daily_visitors - 50) / 3.33
        elif daily_visitors >= 20:
            exposure_score = 25 + (daily_visitors - 20) / 2
        elif daily_visitors >= 5:
            exposure_score = 10 + (daily_visitors - 5) * 1
        else:
            exposure_score = daily_visitors * 2

        # 2. 활동 지수 (100점 만점) - 보조 지표
        # 최근 포스팅 활동 (적정 빈도가 최고점)
        if recent_posts >= 120:  # 스팸 의심
            activity_score = 40
        elif recent_posts >= 60:
            activity_score = 70 + (90 - recent_posts)
        elif recent_posts >= 30:
            activity_score = 60 + (recent_posts - 30) * 0.33
        elif recent_posts >= 10:
            activity_score = 40 + (recent_posts - 10) * 1
        else:
            activity_score = recent_posts * 4

        # 3. 신뢰 지수 (100점 만점) - 보조 지표
        # 이웃, 누적 방문자, 총 게시물
        trust_score = 0
        if neighbors > 0:
            trust_score += min(30, 10 * math.log10(neighbors + 1))
        if total_visitors > 0:
            trust_score += min(40, 8 * math.log10(total_visitors + 1))
        if total_posts > 0:
            trust_score += min(30, 10 * math.log10(total_posts + 1))

        # 4. 종합 점수 (노출 70%, 활동 15%, 신뢰 15%)
        total_score = (exposure_score * 0.7) + (activity_score * 0.15) + (trust_score * 0.15)

        # 노출이 낮으면 상한선 적용
        if exposure_score < 20:
            total_score = min(total_score, 35)  # 일반 이하
        elif exposure_score < 40:
            total_score = min(total_score, 50)  # 준최6 이하

        # 5. 등급 결정 (NSIDE 스타일: 저품 → 일반 → 준최1-7 → NB → 최적)
        if total_score >= 85:
            grade = '최적'
            level = 'optimal'
            color = '#00C853'
        elif total_score >= 80:
            grade = 'NB'
            level = 'nb'
            color = '#00E676'
        elif total_score >= 75:
            grade = '준최1'
            level = 'semi1'
            color = '#69F0AE'
        elif total_score >= 70:
            grade = '준최2'
            level = 'semi2'
            color = '#B9F6CA'
        elif total_score >= 65:
            grade = '준최3'
            level = 'semi3'
            color = '#FFC107'
        elif total_score >= 60:
            grade = '준최4'
            level = 'semi4'
            color = '#FFD54F'
        elif total_score >= 55:
            grade = '준최5'
            level = 'semi5'
            color = '#FFE082'
        elif total_score >= 50:
            grade = '준최6'
            level = 'semi6'
            color = '#FFAB91'
        elif total_score >= 45:
            grade = '준최7'
            level = 'semi7'
            color = '#FF8A65'
        elif total_score >= 30:
            grade = '일반'
            level = 'normal'
            color = '#9E9E9E'
        else:
            grade = '저품'
            level = 'low'
            color = '#F44336'

        # 데이터 신뢰도 판단 (7일 기준, 당일 제외)
        if weekly_count >= 7:
            data_reliability = 'high'  # 7일: 높음
            reliability_msg = f'{weekly_count}일 평균 데이터 (신뢰도 높음)'
        elif weekly_count >= 3:
            data_reliability = 'medium'  # 3~6일: 중간
            reliability_msg = f'{weekly_count}일 평균 데이터 (신뢰도 보통)'
        else:
            data_reliability = 'low'  # 3일 미만: 낮음
            reliability_msg = '분석 데이터 부족 (3일 이상 분석 필요)'

        return {
            'grade': grade,
            'level': level,
            'score': round(total_score, 2),
            'color': color,
            'breakdown': {
                'exposure': round(exposure_score, 2),
                'activity': round(activity_score, 2),
                'trust': round(trust_score, 2)
            },
            'detail': {
                'daily_visitors': daily_visitors,
                'total_visitors': total_visitors,
                'recent_30days_posts': recent_posts,
                'total_posts': total_posts,
                'neighbors': neighbors
            },
            'visitor_source': visitor_source,
            'data_reliability': data_reliability,
            'reliability_msg': reliability_msg,
            'weekly_count': weekly_count
        }


# 크롤러 인스턴스
naver_crawler = NaverBlogCrawler()


# API 엔드포인트
@app.route('/api/analyze', methods=['GET'])
def analyze_blog():
    """블로그 분석 API - 네이버 블로그 전용"""
    blog_id = request.args.get('blog_id', '').strip()

    if not blog_id:
        return jsonify({'error': '블로그 ID를 입력해주세요.'}), 400

    # URL에서 블로그 ID 추출
    if 'blog.naver.com' in blog_id:
        blog_id = blog_id.split('blog.naver.com/')[1].split('/')[0].split('?')[0]

    # 주간 평균 파라미터 받기
    weekly_avg = request.args.get('weekly_avg', type=int, default=0)
    weekly_count = request.args.get('weekly_count', type=int, default=0)

    result = naver_crawler.crawl(blog_id, weekly_avg=weekly_avg, weekly_count=weekly_count)
    result['platform'] = 'naver'
    result['weekly_avg_used'] = weekly_avg if weekly_count >= 2 else 0
    result['weekly_count'] = weekly_count

    return jsonify(result)


@app.route('/api/health')
def health_check():
    """서버 상태 확인"""
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat()})


@app.route('/api/trends')
def get_trending_keywords():
    """실시간 인기 검색어/트렌드 키워드 API (Google Trends + 네이버)"""
    try:
        trends = []

        # 방법 1: Google Trends 관련 검색어 (인기 카테고리별)
        try:
            from pytrends.request import TrendReq
            import random
            pytrends = TrendReq(hl='ko', tz=540, timeout=(10, 25))

            # 블로그 인기 카테고리 키워드로 급상승 검색어 수집
            seed_keywords = ['맛집', '여행', '카페', '다이어트', '인테리어']
            random.shuffle(seed_keywords)

            for seed in seed_keywords[:2]:  # 2개 카테고리만 사용 (속도)
                try:
                    pytrends.build_payload([seed], cat=0, timeframe='now 1-d', geo='KR')
                    related = pytrends.related_queries()

                    if seed in related and related[seed]['rising'] is not None:
                        rising_df = related[seed]['rising']
                        for _, row in rising_df.head(5).iterrows():
                            keyword = row['query']
                            if keyword not in [t['keyword'] for t in trends]:
                                trends.append({
                                    'keyword': keyword,
                                    'category': seed,
                                    'rank': len(trends) + 1,
                                    'source': 'google'
                                })
                except:
                    continue

        except Exception as e:
            print(f"Google Trends error: {e}")

        # 방법 2: 네이버 데이터랩 쇼핑 인사이트 (보조)
        if len(trends) < 5:
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'application/json',
                }
                shopping_url = 'https://datalab.naver.com/shoppingInsight/getKeywordRank.naver'
                shopping_data = {'cid': 'ALL'}
                resp = requests.post(shopping_url, data=shopping_data, headers=headers, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    if 'result' in data:
                        for idx, item in enumerate(data['result'][:10]):
                            trends.append({
                                'keyword': item.get('keyword', ''),
                                'category': '쇼핑',
                                'rank': len(trends) + 1,
                                'source': 'naver'
                            })
            except Exception as e:
                print(f"Naver DataLab error: {e}")

        # 방법 3: 기본 블로그 인기 키워드 (백업)
        if len(trends) < 5:
            blog_trends = [
                {'keyword': '맛집 추천', 'category': '맛집', 'rank': 1, 'source': 'default'},
                {'keyword': '여행 코스', 'category': '여행', 'rank': 2, 'source': 'default'},
                {'keyword': '다이어트 식단', 'category': '건강', 'rank': 3, 'source': 'default'},
                {'keyword': '주식 투자', 'category': '재테크', 'rank': 4, 'source': 'default'},
                {'keyword': '인테리어 팁', 'category': '라이프', 'rank': 5, 'source': 'default'},
                {'keyword': '육아 정보', 'category': '육아', 'rank': 6, 'source': 'default'},
                {'keyword': '자기계발 책 추천', 'category': '도서', 'rank': 7, 'source': 'default'},
                {'keyword': '운동 루틴', 'category': '운동', 'rank': 8, 'source': 'default'},
                {'keyword': '카페 추천', 'category': '카페', 'rank': 9, 'source': 'default'},
                {'keyword': '부업 방법', 'category': '재테크', 'rank': 10, 'source': 'default'},
            ]
            trends = blog_trends

        # 출처 정보 추가
        source_info = 'google' if trends and trends[0].get('source') == 'google' else 'naver' if trends and trends[0].get('source') == 'naver' else 'default'

        return jsonify({
            'trends': trends[:15],
            'updated': datetime.now().isoformat(),
            'source': source_info
        })

    except Exception as e:
        print(f"Trends API error: {e}")
        return jsonify({'trends': [], 'error': str(e)})


@app.route('/api/competitor')
def analyze_competitor():
    """경쟁 블로그 분석 API - 같은 키워드 상위 노출 블로그와 비교"""
    keyword = request.args.get('keyword', '').strip()
    my_blog_id = request.args.get('blog_id', '').strip()

    if not keyword:
        return jsonify({'error': '키워드를 입력해주세요.'}), 400

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }

        # 네이버 블로그 검색
        search_url = f'https://search.naver.com/search.naver?where=blog&query={urllib.parse.quote(keyword)}'
        response = requests.get(search_url, headers=headers, timeout=10)

        competitors = []

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')

            # 검색 결과에서 상위 블로그 추출
            blog_items = soup.select('.api_txt_lines.total_tit, .title_link')[:5]

            for idx, item in enumerate(blog_items):
                try:
                    link = item.get('href', '')
                    title = item.get_text(strip=True)

                    # 블로그 ID 추출
                    blog_id_match = re.search(r'blog\.naver\.com/([a-zA-Z0-9_-]+)', link)
                    if blog_id_match:
                        competitor_id = blog_id_match.group(1)
                        competitors.append({
                            'rank': idx + 1,
                            'blog_id': competitor_id,
                            'title': title[:50],
                            'link': link,
                            'is_mine': competitor_id == my_blog_id
                        })
                except:
                    continue

        # 내 블로그 순위 확인
        my_rank = None
        for comp in competitors:
            if comp.get('is_mine'):
                my_rank = comp['rank']
                break

        return jsonify({
            'keyword': keyword,
            'competitors': competitors,
            'my_rank': my_rank,
            'total_competitors': len(competitors)
        })

    except Exception as e:
        print(f"Competitor API error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/seo-score')
def calculate_seo_score():
    """SEO 점수 계산 API"""
    blog_id = request.args.get('blog_id', '').strip()

    if not blog_id:
        return jsonify({'error': '블로그 ID를 입력해주세요.'}), 400

    try:
        # 블로그 분석 결과 가져오기
        result = naver_crawler.crawl(blog_id)

        # SEO 점수 계산
        seo_score = {
            'total': 0,
            'breakdown': {},
            'recommendations': []
        }

        posts = result.get('posts_with_index', [])

        if posts:
            # 1. 제목 SEO (25점)
            title_scores = []
            for post in posts[:10]:
                title = post.get('title', '')
                score = 0
                if 20 <= len(title) <= 45:
                    score += 10
                elif 15 <= len(title) <= 50:
                    score += 5
                if post.get('keyword') and post['keyword'] in title:
                    score += 15
                title_scores.append(score)
            title_avg = sum(title_scores) / len(title_scores) if title_scores else 0
            seo_score['breakdown']['title'] = round(title_avg, 1)

            # 2. 이미지 SEO (25점)
            image_scores = []
            for post in posts[:10]:
                images = post.get('images', 0)
                score = 0
                if 5 <= images <= 15:
                    score += 15
                elif 3 <= images < 5:
                    score += 10
                elif images > 0:
                    score += 5
                # ALT 태그 점수
                image_seo = post.get('image_seo', {})
                if image_seo.get('alt_quality') == 'excellent':
                    score += 10
                elif image_seo.get('alt_quality') == 'good':
                    score += 7
                elif image_seo.get('alt_quality') == 'average':
                    score += 4
                image_scores.append(score)
            image_avg = sum(image_scores) / len(image_scores) if image_scores else 0
            seo_score['breakdown']['image'] = round(image_avg, 1)

            # 3. 콘텐츠 SEO (25점)
            content_scores = []
            for post in posts[:10]:
                char_count = post.get('char_count', 0)
                score = 0
                if char_count >= 2000:
                    score += 15
                elif char_count >= 1500:
                    score += 10
                elif char_count >= 1000:
                    score += 5
                # 소제목 점수
                if post.get('subheading_count', 0) >= 2:
                    score += 10
                elif post.get('subheading_count', 0) > 0:
                    score += 5
                content_scores.append(score)
            content_avg = sum(content_scores) / len(content_scores) if content_scores else 0
            seo_score['breakdown']['content'] = round(content_avg, 1)

            # 4. 노출 SEO (25점)
            indexed = sum(1 for p in posts[:10] if p.get('exposure') == 'indexed')
            exposure_score = (indexed / min(10, len(posts))) * 25
            seo_score['breakdown']['exposure'] = round(exposure_score, 1)

            # 총점 계산
            seo_score['total'] = round(
                seo_score['breakdown']['title'] +
                seo_score['breakdown']['image'] +
                seo_score['breakdown']['content'] +
                seo_score['breakdown']['exposure'],
                1
            )

            # 권장사항 생성
            if seo_score['breakdown']['title'] < 15:
                seo_score['recommendations'].append('제목에 키워드를 포함하고 20-45자로 작성하세요')
            if seo_score['breakdown']['image'] < 15:
                seo_score['recommendations'].append('이미지 5-15개 사용 및 ALT 태그 설정을 권장합니다')
            if seo_score['breakdown']['content'] < 15:
                seo_score['recommendations'].append('본문 2000자 이상, 소제목 2개 이상 사용을 권장합니다')
            if seo_score['breakdown']['exposure'] < 15:
                seo_score['recommendations'].append('롱테일 키워드로 검색 노출률을 높이세요')

        return jsonify(seo_score)

    except Exception as e:
        print(f"SEO Score API error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/suggest')
def keyword_suggest():
    """네이버 연관 키워드 추천 API"""
    keyword = request.args.get('keyword', '').strip()

    if not keyword:
        return jsonify({'error': '키워드를 입력해주세요.', 'suggestions': []})

    try:
        # 네이버 모바일 검색 자동완성 API (더 안정적)
        suggest_url = f'https://mac.search.naver.com/mobile/ac?st=100&frm=mobile_sug&q={urllib.parse.quote(keyword)}'

        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15',
            'Accept': 'application/json',
        }

        response = requests.get(suggest_url, headers=headers, timeout=5)

        if response.status_code == 200:
            data = response.json()
            suggestions = []

            # 자동완성 결과에서 키워드 추출
            if 'items' in data and len(data['items']) > 0:
                for item in data['items'][0]:
                    if isinstance(item, list) and len(item) > 0:
                        suggestions.append(item[0])

            # 중복 제거 및 최대 15개
            unique_suggestions = list(dict.fromkeys(suggestions))[:15]

            return jsonify({'suggestions': unique_suggestions, 'source': 'naver'})
        else:
            return jsonify({'suggestions': [], 'error': '검색 실패'})

    except Exception as e:
        print(f"Keyword suggest error: {e}")
        return jsonify({'suggestions': [], 'error': str(e)})


# ============ Supabase DB API ============

@app.route('/api/history/save', methods=['POST'])
def save_analysis_history():
    """분석 결과를 Supabase에 저장"""
    if not SUPABASE_KEY:
        return jsonify({'success': False, 'error': 'DB 연결 안됨'}), 500

    try:
        data = request.get_json()
        blog_id = data.get('blog_id')
        analysis_data = data.get('analysis_data')

        if not blog_id or not analysis_data:
            return jsonify({'success': False, 'error': '필수 데이터 누락'}), 400

        # 저장할 데이터 구성
        record = {
            'blog_id': blog_id,
            'blog_name': analysis_data.get('blog_name', ''),
            'daily_visitors': analysis_data.get('daily_visitors', 0),
            'total_posts': analysis_data.get('total_posts', 0),
            'neighbors': analysis_data.get('neighbors', 0),
            'index_score': analysis_data.get('index', {}).get('score', 0),
            'index_grade': analysis_data.get('index', {}).get('grade', ''),
            'analyzed_at': datetime.now().isoformat(),
            'full_data': json.dumps(analysis_data, ensure_ascii=False)
        }

        # Supabase REST API로 저장
        result = supabase_request('POST', 'blog_history', data=record)

        if result:
            return jsonify({'success': True, 'data': result})
        else:
            return jsonify({'success': False, 'error': 'DB 저장 실패'}), 500

    except Exception as e:
        print(f"Save history error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/history/<blog_id>')
def get_analysis_history(blog_id):
    """특정 블로그의 분석 히스토리 조회"""
    if not SUPABASE_KEY:
        return jsonify({'success': False, 'error': 'DB 연결 안됨', 'history': []}), 500

    try:
        # 최근 30일 데이터 조회
        params = {
            'select': '*',
            'blog_id': f'eq.{blog_id}',
            'order': 'analyzed_at.desc',
            'limit': '30'
        }
        result = supabase_request('GET', 'blog_history', params=params)

        return jsonify({'success': True, 'history': result or []})

    except Exception as e:
        print(f"Get history error: {e}")
        return jsonify({'success': False, 'error': str(e), 'history': []}), 500


@app.route('/api/history/recent')
def get_recent_blogs():
    """최근 분석된 블로그 목록 조회"""
    if not SUPABASE_KEY:
        return jsonify({'success': False, 'error': 'DB 연결 안됨', 'blogs': []}), 500

    try:
        # 최근 분석된 블로그 (중복 제거, 최신순)
        params = {
            'select': 'blog_id,blog_name,index_grade,daily_visitors,analyzed_at',
            'order': 'analyzed_at.desc',
            'limit': '50'
        }
        result = supabase_request('GET', 'blog_history', params=params)

        # 블로그 ID별 최신 데이터만 추출
        seen = set()
        unique_blogs = []
        for item in (result or []):
            if item['blog_id'] not in seen:
                seen.add(item['blog_id'])
                unique_blogs.append(item)
                if len(unique_blogs) >= 10:
                    break

        return jsonify({'success': True, 'blogs': unique_blogs})

    except Exception as e:
        print(f"Get recent blogs error: {e}")
        return jsonify({'success': False, 'error': str(e), 'blogs': []}), 500


# =====================================================
# 커뮤니티 API
# =====================================================

@app.route('/api/community/posts', methods=['GET'])
def get_community_posts():
    """커뮤니티 게시글 목록 조회"""
    if not SUPABASE_KEY:
        return jsonify({'success': False, 'posts': [], 'total': 0, 'page': 1})

    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 10))
        category = request.args.get('category', '')

        offset = (page - 1) * limit

        # 게시글 조회
        params = {
            'select': '*',
            'order': 'created_at.desc',
            'offset': str(offset),
            'limit': str(limit)
        }

        if category and category != 'all':
            params['category'] = f'eq.{category}'

        result = supabase_request('GET', 'community_posts', params=params)

        # 전체 개수 조회
        count_params = {'select': 'id'}
        if category and category != 'all':
            count_params['category'] = f'eq.{category}'
        count_result = supabase_request('GET', 'community_posts', params=count_params)
        total = len(count_result) if count_result else 0

        return jsonify({
            'success': True,
            'posts': result or [],
            'total': total,
            'page': page
        })

    except Exception as e:
        print(f"Get community posts error: {e}")
        return jsonify({'success': False, 'posts': [], 'total': 0, 'page': 1, 'error': str(e)})


@app.route('/api/community/posts', methods=['POST'])
def create_community_post():
    """커뮤니티 게시글 작성"""
    if not SUPABASE_KEY:
        return jsonify({'success': False, 'error': 'DB 연결 안됨'})

    try:
        data = request.json
        nickname = data.get('nickname', '익명')[:20]
        category = data.get('category', 'question')
        title = data.get('title', '')[:100]
        content = data.get('content', '')[:5000]

        if not title or not content:
            return jsonify({'success': False, 'error': '제목과 내용을 입력해주세요.'})

        # 게시글 저장
        post_data = {
            'nickname': nickname,
            'category': category,
            'title': title,
            'content': content,
            'likes': 0,
            'comments': 0
        }

        result = supabase_request('POST', 'community_posts', data=post_data)

        if result:
            return jsonify({'success': True, 'post': result[0] if isinstance(result, list) else result})
        else:
            return jsonify({'success': False, 'error': '게시글 저장 실패'})

    except Exception as e:
        print(f"Create community post error: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/community/posts/<int:post_id>')
def get_community_post(post_id):
    """커뮤니티 게시글 상세 조회"""
    if not SUPABASE_KEY:
        return jsonify({'success': False, 'error': 'DB 연결 안됨'})

    try:
        params = {
            'select': '*',
            'id': f'eq.{post_id}'
        }
        result = supabase_request('GET', 'community_posts', params=params)

        if result and len(result) > 0:
            return jsonify({'success': True, 'post': result[0]})
        else:
            return jsonify({'success': False, 'error': '게시글을 찾을 수 없습니다.'})

    except Exception as e:
        print(f"Get community post error: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/community/posts/<int:post_id>/like', methods=['POST'])
def like_community_post(post_id):
    """커뮤니티 게시글 좋아요"""
    if not SUPABASE_KEY:
        return jsonify({'success': False, 'error': 'DB 연결 안됨'})

    try:
        # 현재 좋아요 수 조회
        params = {'select': 'likes', 'id': f'eq.{post_id}'}
        result = supabase_request('GET', 'community_posts', params=params)

        if result and len(result) > 0:
            current_likes = result[0].get('likes', 0)
            # 좋아요 증가
            update_data = {'likes': current_likes + 1}
            supabase_request('PATCH', f'community_posts?id=eq.{post_id}', data=update_data)
            return jsonify({'success': True, 'likes': current_likes + 1})
        else:
            return jsonify({'success': False, 'error': '게시글을 찾을 수 없습니다.'})

    except Exception as e:
        print(f"Like community post error: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/download/extension')
def download_extension():
    """크롬 확장 프로그램 다운로드"""
    import os
    zip_path = os.path.join(os.path.dirname(__file__), 'blog-stats-extension.zip')
    if os.path.exists(zip_path):
        return send_file(zip_path, as_attachment=True, download_name='blog-stats-extension.zip')
    return "파일을 찾을 수 없습니다.", 404


# =====================================================
# 법적 페이지 (개인정보처리방침, 이용약관, 면책조항)
# =====================================================
def get_legal_page_template(title, content):
    """법적 페이지 공통 템플릿"""
    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - 블로그 지수 분석기</title>
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Noto Sans KR', sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            min-height: 100vh;
            color: #fff;
            line-height: 1.8;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
            padding: 40px 20px;
        }}
        .back-btn {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            color: #667eea;
            text-decoration: none;
            margin-bottom: 30px;
            font-size: 14px;
        }}
        .back-btn:hover {{ text-decoration: underline; }}
        h1 {{
            font-size: 28px;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }}
        h2 {{
            font-size: 18px;
            margin: 30px 0 15px;
            color: #667eea;
        }}
        p, li {{
            color: rgba(255,255,255,0.8);
            margin-bottom: 12px;
        }}
        ul {{
            padding-left: 20px;
            margin-bottom: 20px;
        }}
        .update-date {{
            font-size: 13px;
            color: rgba(255,255,255,0.5);
            margin-bottom: 30px;
        }}
        .section {{
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <a href="/" class="back-btn">← 메인으로 돌아가기</a>
        <h1>{title}</h1>
        <p class="update-date">최종 업데이트: 2025년 1월</p>
        {content}
    </div>
</body>
</html>'''

@app.route('/privacy')
def privacy_page():
    """개인정보처리방침 페이지"""
    content = '''
        <div class="section">
            <h2>1. 개인정보 수집 항목</h2>
            <p>본 서비스는 별도의 회원가입 없이 이용 가능하며, <strong>개인정보를 수집하지 않습니다.</strong></p>
            <ul>
                <li>블로그 아이디: 분석 목적으로만 사용되며, 서버에 저장되지 않습니다.</li>
                <li>분석 기록: 사용자의 브라우저(LocalStorage)에만 저장됩니다.</li>
            </ul>
        </div>

        <div class="section">
            <h2>2. 쿠키 및 분석 도구</h2>
            <p>본 서비스는 다음과 같은 목적으로 쿠키를 사용할 수 있습니다:</p>
            <ul>
                <li>테마 설정 저장 (다크모드/라이트모드)</li>
                <li>광고 서비스 제공 (카카오 애드핏)</li>
            </ul>
        </div>

        <div class="section">
            <h2>3. 제3자 서비스</h2>
            <p>본 서비스는 다음의 제3자 서비스를 이용합니다:</p>
            <ul>
                <li><strong>카카오 애드핏:</strong> 광고 제공 목적</li>
                <li><strong>Google Fonts:</strong> 웹폰트 제공</li>
            </ul>
            <p>각 서비스의 개인정보 처리에 대해서는 해당 서비스의 개인정보처리방침을 참조하시기 바랍니다.</p>
        </div>

        <div class="section">
            <h2>4. 데이터 보관</h2>
            <p>본 서비스는 사용자 데이터를 서버에 저장하지 않습니다. 모든 분석은 실시간으로 처리되며, 결과는 사용자의 브라우저에만 임시 저장됩니다.</p>
        </div>

        <div class="section">
            <h2>5. 문의</h2>
            <p>개인정보 관련 문의사항이 있으시면 서비스 내 커뮤니티를 통해 문의해 주시기 바랍니다.</p>
        </div>
    '''
    return get_legal_page_template('개인정보처리방침', content)

@app.route('/terms')
def terms_page():
    """이용약관 페이지"""
    content = '''
        <div class="section">
            <h2>제1조 (목적)</h2>
            <p>본 약관은 블로그 지수 분석기(이하 "서비스")의 이용과 관련하여 서비스 제공자와 이용자 간의 권리, 의무 및 책임사항을 규정함을 목적으로 합니다.</p>
        </div>

        <div class="section">
            <h2>제2조 (서비스의 내용)</h2>
            <p>본 서비스는 다음과 같은 기능을 제공합니다:</p>
            <ul>
                <li>네이버 블로그 분석 및 지수 산출</li>
                <li>포스팅 진단 및 최적화 조언</li>
                <li>트렌드 키워드 정보 제공</li>
                <li>블로거 커뮤니티</li>
            </ul>
        </div>

        <div class="section">
            <h2>제3조 (서비스 이용)</h2>
            <ul>
                <li>본 서비스는 무료로 제공됩니다.</li>
                <li>별도의 회원가입 없이 이용 가능합니다.</li>
                <li>서비스 이용 시 관련 법령을 준수해야 합니다.</li>
            </ul>
        </div>

        <div class="section">
            <h2>제4조 (금지행위)</h2>
            <p>이용자는 다음 행위를 해서는 안 됩니다:</p>
            <ul>
                <li>서비스의 안정적 운영을 방해하는 행위</li>
                <li>자동화된 수단을 이용한 과도한 요청</li>
                <li>타인의 블로그를 악의적 목적으로 분석하는 행위</li>
                <li>서비스를 이용한 불법적 활동</li>
            </ul>
        </div>

        <div class="section">
            <h2>제5조 (면책)</h2>
            <ul>
                <li>본 서비스는 참고용 정보를 제공하며, 정확성을 보장하지 않습니다.</li>
                <li>분석 결과를 바탕으로 한 의사결정의 책임은 이용자에게 있습니다.</li>
                <li>서비스 장애, 데이터 손실 등에 대해 책임지지 않습니다.</li>
            </ul>
        </div>

        <div class="section">
            <h2>제6조 (서비스 변경 및 중단)</h2>
            <p>서비스 제공자는 필요한 경우 서비스의 내용을 변경하거나 중단할 수 있으며, 이에 대해 별도의 보상을 하지 않습니다.</p>
        </div>

        <div class="section">
            <h2>제7조 (약관의 변경)</h2>
            <p>본 약관은 필요에 따라 변경될 수 있으며, 변경된 약관은 서비스 내 공지를 통해 효력이 발생합니다.</p>
        </div>
    '''
    return get_legal_page_template('이용약관', content)

@app.route('/disclaimer')
def disclaimer_page():
    """면책조항 페이지"""
    content = '''
        <div class="section">
            <h2>서비스 성격</h2>
            <p>블로그 지수 분석기는 네이버 블로그의 공개된 정보를 수집·분석하여 <strong>참고용 지표</strong>를 제공하는 서비스입니다.</p>
        </div>

        <div class="section">
            <h2>데이터 정확성</h2>
            <ul>
                <li>본 서비스에서 제공하는 모든 지수, 점수, 분석 결과는 자체 알고리즘에 의한 <strong>추정치</strong>입니다.</li>
                <li>네이버의 공식 지수나 통계가 아니며, 네이버와 무관한 독립 서비스입니다.</li>
                <li>실제 블로그 성과와 차이가 있을 수 있습니다.</li>
            </ul>
        </div>

        <div class="section">
            <h2>책임 제한</h2>
            <ul>
                <li>분석 결과를 바탕으로 한 모든 의사결정의 책임은 이용자 본인에게 있습니다.</li>
                <li>서비스 이용으로 인한 직·간접적 손해에 대해 책임지지 않습니다.</li>
                <li>제3자 서비스(네이버, 카카오 등)의 정책 변경으로 인한 서비스 오류에 대해 책임지지 않습니다.</li>
            </ul>
        </div>

        <div class="section">
            <h2>데이터 출처</h2>
            <ul>
                <li>블로그 정보: 네이버 블로그 RSS 피드 및 공개 페이지</li>
                <li>트렌드 키워드: Google Trends 및 자체 데이터</li>
            </ul>
            <p>모든 데이터는 공개적으로 접근 가능한 정보만을 수집합니다.</p>
        </div>

        <div class="section">
            <h2>서비스 가용성</h2>
            <ul>
                <li>서비스는 사전 고지 없이 변경, 중단될 수 있습니다.</li>
                <li>서버 점검, 장애 등으로 일시적으로 이용이 제한될 수 있습니다.</li>
                <li>서비스 중단으로 인한 손해에 대해 배상하지 않습니다.</li>
            </ul>
        </div>

        <div class="section">
            <h2>지적 재산권</h2>
            <p>본 서비스의 디자인, 코드, 콘텐츠에 대한 권리는 서비스 제공자에게 있습니다. 무단 복제, 배포를 금지합니다.</p>
        </div>
    '''
    return get_legal_page_template('면책조항', content)


# =====================================================
# 크롬 확장 프로그램 페이지
# =====================================================
@app.route('/extension')
def extension_page():
    """크롬 확장 프로그램 안내 페이지"""
    return '''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>블로그 통계 확장 프로그램 - 블로그 지수 분석기</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            color: #e0e0e0;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            padding: 40px 20px;
        }
        .back-btn {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            color: #667eea;
            text-decoration: none;
            margin-bottom: 30px;
            font-size: 14px;
        }
        .back-btn:hover { text-decoration: underline; }
        .header {
            text-align: center;
            margin-bottom: 40px;
        }
        .header-icon {
            font-size: 80px;
            margin-bottom: 20px;
        }
        .header h1 {
            font-size: 32px;
            margin-bottom: 10px;
            background: linear-gradient(135deg, #667eea, #764ba2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        .header p { color: #888; font-size: 16px; }
        .card {
            background: rgba(255,255,255,0.05);
            border-radius: 16px;
            padding: 30px;
            margin-bottom: 20px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .card h2 {
            font-size: 20px;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .feature-list {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        .feature-item {
            background: rgba(102,126,234,0.1);
            padding: 15px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .feature-item span:first-child { font-size: 24px; }
        .steps {
            counter-reset: step;
        }
        .step {
            display: flex;
            gap: 20px;
            margin-bottom: 25px;
            padding-bottom: 25px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .step:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
        .step-number {
            width: 40px;
            height: 40px;
            background: linear-gradient(135deg, #667eea, #764ba2);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            flex-shrink: 0;
        }
        .step-content h3 {
            font-size: 16px;
            margin-bottom: 8px;
        }
        .step-content p {
            color: #888;
            font-size: 14px;
            line-height: 1.6;
        }
        .download-btn {
            display: inline-flex;
            align-items: center;
            gap: 10px;
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            padding: 16px 32px;
            border-radius: 12px;
            text-decoration: none;
            font-weight: 600;
            font-size: 18px;
            margin: 20px 0;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .download-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 30px rgba(102,126,234,0.3);
        }
        .note {
            background: rgba(255,193,7,0.1);
            border-left: 4px solid #ffc107;
            padding: 15px 20px;
            border-radius: 0 12px 12px 0;
            margin-top: 20px;
        }
        .note-title {
            font-weight: 600;
            color: #ffc107;
            margin-bottom: 8px;
        }
        .note p { color: #ccc; font-size: 14px; line-height: 1.6; }
        .screenshot {
            background: rgba(0,0,0,0.3);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            margin: 20px 0;
        }
        .screenshot-placeholder {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 8px;
            padding: 40px;
            color: white;
        }
        .faq { margin-top: 10px; }
        .faq-item {
            margin-bottom: 15px;
        }
        .faq-item h4 {
            color: #667eea;
            font-size: 15px;
            margin-bottom: 5px;
        }
        .faq-item p { color: #888; font-size: 14px; line-height: 1.5; }
    </style>
</head>
<body>
    <div class="container">
        <a href="/" class="back-btn">← 메인으로 돌아가기</a>

        <div class="header">
            <div class="header-icon">🧩</div>
            <h1>블로그 통계 확장 프로그램</h1>
            <p>네이버 블로그 관리자 페이지에서 통계를 쉽게 확인하세요</p>
        </div>

        <div class="card">
            <h2>✨ 주요 기능</h2>
            <div class="feature-list">
                <div class="feature-item">
                    <span>📊</span>
                    <span>오늘/어제 방문자 수</span>
                </div>
                <div class="feature-item">
                    <span>📈</span>
                    <span>주간/월간 방문 추이</span>
                </div>
                <div class="feature-item">
                    <span>🏆</span>
                    <span>인기 게시글 TOP 5</span>
                </div>
                <div class="feature-item">
                    <span>📁</span>
                    <span>데이터 JSON 내보내기</span>
                </div>
            </div>
        </div>

        <div class="card">
            <h2>📥 다운로드</h2>
            <p style="color: #888; margin-bottom: 15px;">아래 버튼을 클릭하여 확장 프로그램 ZIP 파일을 다운로드하세요.</p>
            <a href="/download/extension" class="download-btn">
                <span>⬇️</span>
                <span>확장 프로그램 다운로드</span>
            </a>
            <p style="color: #666; font-size: 13px;">파일 크기: 약 12KB</p>
        </div>

        <div class="card">
            <h2>🔧 설치 방법</h2>
            <div class="steps">
                <div class="step">
                    <div class="step-number">1</div>
                    <div class="step-content">
                        <h3>ZIP 파일 다운로드 & 압축 해제</h3>
                        <p>위의 다운로드 버튼을 클릭하여 ZIP 파일을 받고, 원하는 위치에 압축을 해제합니다.</p>
                    </div>
                </div>
                <div class="step">
                    <div class="step-number">2</div>
                    <div class="step-content">
                        <h3>크롬 확장 프로그램 페이지 열기</h3>
                        <p>크롬 브라우저에서 <strong>chrome://extensions</strong>를 입력하거나, 메뉴 → 도구 더보기 → 확장 프로그램을 클릭합니다.</p>
                    </div>
                </div>
                <div class="step">
                    <div class="step-number">3</div>
                    <div class="step-content">
                        <h3>개발자 모드 활성화</h3>
                        <p>우측 상단의 <strong>"개발자 모드"</strong> 토글을 켭니다.</p>
                    </div>
                </div>
                <div class="step">
                    <div class="step-number">4</div>
                    <div class="step-content">
                        <h3>압축해제된 확장 프로그램 로드</h3>
                        <p><strong>"압축해제된 확장 프로그램을 로드합니다"</strong> 버튼을 클릭하고, 압축을 푼 폴더를 선택합니다.</p>
                    </div>
                </div>
                <div class="step">
                    <div class="step-number">5</div>
                    <div class="step-content">
                        <h3>설치 완료!</h3>
                        <p>브라우저 우측 상단에 📊 아이콘이 나타나면 설치가 완료된 것입니다. 네이버 블로그 관리 페이지에서 클릭하여 사용하세요.</p>
                    </div>
                </div>
            </div>
        </div>

        <div class="card">
            <h2>💡 사용 방법</h2>
            <div class="steps">
                <div class="step">
                    <div class="step-number">1</div>
                    <div class="step-content">
                        <h3>네이버 블로그 관리 페이지 접속</h3>
                        <p><a href="https://admin.blog.naver.com/" target="_blank" style="color: #667eea;">admin.blog.naver.com</a>에 로그인합니다.</p>
                    </div>
                </div>
                <div class="step">
                    <div class="step-number">2</div>
                    <div class="step-content">
                        <h3>확장 프로그램 아이콘 클릭</h3>
                        <p>브라우저 우측 상단의 📊 아이콘을 클릭하면 팝업이 열리며 통계가 표시됩니다.</p>
                    </div>
                </div>
            </div>

            <div class="note">
                <div class="note-title">⚠️ 참고사항</div>
                <p>이 확장 프로그램은 <strong>본인 블로그의 통계만</strong> 확인할 수 있습니다. 네이버 블로그 관리 페이지에 로그인한 상태에서만 작동합니다.</p>
            </div>
        </div>

        <div class="card">
            <h2>❓ 자주 묻는 질문</h2>
            <div class="faq">
                <div class="faq-item">
                    <h4>Q. 다른 사람의 블로그 통계도 볼 수 있나요?</h4>
                    <p>아니요, 본인이 로그인한 블로그의 통계만 확인할 수 있습니다. 다른 블로그의 방문자 수는 공개되지 않는 정보입니다.</p>
                </div>
                <div class="faq-item">
                    <h4>Q. 크롬 외 다른 브라우저에서도 사용할 수 있나요?</h4>
                    <p>Edge, Whale 등 크로미움 기반 브라우저에서도 동일한 방법으로 설치 가능합니다.</p>
                </div>
                <div class="faq-item">
                    <h4>Q. 안전한가요?</h4>
                    <p>네, 이 확장 프로그램은 네이버 블로그 관리 페이지에서만 작동하며, 어떠한 개인정보도 외부로 전송하지 않습니다.</p>
                </div>
            </div>
        </div>
    </div>
</body>
</html>'''


# =====================================================
# 커뮤니티 페이지
# =====================================================
@app.route('/community')
def community_page():
    """커뮤니티 페이지"""
    return '''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>블로거 커뮤니티 - 블로그 지수 분석기</title>
    <meta name="description" content="블로거들의 소통 공간. 질문, 정보공유, 성장일기를 나눠보세요.">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;600;700&display=swap" rel="stylesheet">

    <!-- 카카오 애드핏 -->
    <script async src="https://t1.daumcdn.net/kas/static/ba.min.js"></script>

    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Noto Sans KR', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            min-height: 100vh;
            color: #fff;
        }

        body.light-mode {
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 50%, #dee2e6 100%);
            color: #1a1a2e;
        }

        .container {
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
        }

        /* 헤더 */
        .community-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 20px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
            margin-bottom: 20px;
        }

        .header-left {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .back-btn {
            background: rgba(255,255,255,0.1);
            border: none;
            color: #fff;
            padding: 10px 16px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
            text-decoration: none;
        }

        .back-btn:hover {
            background: rgba(255,255,255,0.2);
        }

        .light-mode .back-btn {
            background: rgba(0,0,0,0.05);
            color: #1a1a2e;
        }

        .page-title {
            font-size: 24px;
            font-weight: 700;
        }

        .theme-toggle {
            background: rgba(255,255,255,0.1);
            border: none;
            font-size: 20px;
            padding: 10px;
            border-radius: 50%;
            cursor: pointer;
            transition: all 0.2s;
        }

        .theme-toggle:hover {
            background: rgba(255,255,255,0.2);
        }

        /* 상단 배너 광고 */
        .ad-banner-top {
            background: rgba(0,0,0,0.2);
            border-radius: 12px;
            padding: 10px;
            text-align: center;
            margin-bottom: 20px;
        }

        .ad-label {
            font-size: 10px;
            color: rgba(255,255,255,0.4);
            margin-bottom: 5px;
        }

        .light-mode .ad-label {
            color: rgba(0,0,0,0.4);
        }

        /* 카테고리 탭 */
        .category-tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            overflow-x: auto;
            padding-bottom: 5px;
        }

        .category-tab {
            padding: 10px 20px;
            background: rgba(255,255,255,0.1);
            border: none;
            border-radius: 25px;
            color: rgba(255,255,255,0.7);
            font-size: 14px;
            cursor: pointer;
            white-space: nowrap;
            transition: all 0.2s;
        }

        .category-tab:hover {
            background: rgba(255,255,255,0.15);
        }

        .category-tab.active {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #fff;
        }

        .light-mode .category-tab {
            background: rgba(0,0,0,0.05);
            color: rgba(0,0,0,0.6);
        }

        .light-mode .category-tab.active {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #fff;
        }

        /* 글쓰기 섹션 */
        .write-section {
            background: rgba(255,255,255,0.05);
            border-radius: 16px;
            margin-bottom: 20px;
            overflow: hidden;
        }

        .light-mode .write-section {
            background: #fff;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }

        .write-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 20px;
            cursor: pointer;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }

        .light-mode .write-header {
            border-bottom: 1px solid rgba(0,0,0,0.1);
        }

        .write-header-title {
            font-size: 15px;
            font-weight: 600;
        }

        .write-arrow {
            transition: transform 0.3s;
        }

        .write-form {
            display: none;
            padding: 20px;
        }

        .write-form.active {
            display: block;
        }

        .form-row {
            display: flex;
            gap: 12px;
            margin-bottom: 12px;
        }

        .form-input {
            flex: 1;
            padding: 12px 16px;
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 10px;
            background: rgba(0,0,0,0.2);
            color: #fff;
            font-size: 14px;
        }

        .light-mode .form-input {
            border: 1px solid rgba(0,0,0,0.15);
            background: #f8f9fa;
            color: #1a1a2e;
        }

        .form-input::placeholder {
            color: rgba(255,255,255,0.4);
        }

        .light-mode .form-input::placeholder {
            color: rgba(0,0,0,0.4);
        }

        .form-select {
            padding: 12px 16px;
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 10px;
            background: rgba(0,0,0,0.2);
            color: #fff;
            font-size: 14px;
            min-width: 120px;
        }

        .light-mode .form-select {
            border: 1px solid rgba(0,0,0,0.15);
            background: #f8f9fa;
            color: #1a1a2e;
        }

        .form-textarea {
            width: 100%;
            padding: 14px 16px;
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 10px;
            background: rgba(0,0,0,0.2);
            color: #fff;
            font-size: 14px;
            resize: vertical;
            min-height: 120px;
            margin-bottom: 12px;
        }

        .light-mode .form-textarea {
            border: 1px solid rgba(0,0,0,0.15);
            background: #f8f9fa;
            color: #1a1a2e;
        }

        .submit-btn {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border: none;
            border-radius: 10px;
            color: #fff;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }

        .submit-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
        }

        /* 글쓰기 아래 광고 */
        .ad-after-write {
            background: rgba(0,0,0,0.2);
            border-radius: 12px;
            padding: 10px;
            text-align: center;
            margin-bottom: 20px;
        }

        /* 게시글 목록 */
        .posts-list {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .post-card {
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            padding: 18px 20px;
            cursor: pointer;
            transition: all 0.2s;
        }

        .post-card:hover {
            background: rgba(255,255,255,0.1);
            transform: translateY(-2px);
        }

        .light-mode .post-card {
            background: #fff;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }

        .light-mode .post-card:hover {
            box-shadow: 0 4px 15px rgba(0,0,0,0.12);
        }

        .post-category-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 15px;
            font-size: 11px;
            font-weight: 600;
            margin-bottom: 10px;
        }

        .post-category-badge.question {
            background: rgba(255, 152, 0, 0.2);
            color: #ffb74d;
        }

        .post-category-badge.info {
            background: rgba(76, 175, 80, 0.2);
            color: #81c784;
        }

        .post-category-badge.diary {
            background: rgba(156, 39, 176, 0.2);
            color: #ba68c8;
        }

        .post-title {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 10px;
            line-height: 1.4;
        }

        .post-meta {
            display: flex;
            align-items: center;
            gap: 16px;
            font-size: 13px;
            color: rgba(255,255,255,0.5);
        }

        .light-mode .post-meta {
            color: rgba(0,0,0,0.5);
        }

        .post-stats {
            display: flex;
            gap: 12px;
            margin-left: auto;
        }

        /* 중간 광고 (게시글 사이) */
        .ad-in-list {
            background: rgba(0,0,0,0.15);
            border-radius: 12px;
            padding: 10px;
            text-align: center;
        }

        .light-mode .ad-in-list {
            background: rgba(0,0,0,0.03);
        }

        /* 페이지네이션 */
        .pagination {
            display: flex;
            justify-content: center;
            gap: 8px;
            margin-top: 30px;
        }

        .page-btn {
            padding: 10px 14px;
            background: rgba(255,255,255,0.1);
            border: none;
            border-radius: 8px;
            color: rgba(255,255,255,0.7);
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
        }

        .page-btn:hover {
            background: rgba(255,255,255,0.15);
        }

        .page-btn.active {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #fff;
        }

        .light-mode .page-btn {
            background: rgba(0,0,0,0.05);
            color: rgba(0,0,0,0.6);
        }

        /* 빈 상태 */
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: rgba(255,255,255,0.5);
        }

        .light-mode .empty-state {
            color: rgba(0,0,0,0.5);
        }

        .empty-icon {
            font-size: 48px;
            margin-bottom: 16px;
        }

        /* 하단 광고 */
        .ad-bottom {
            background: rgba(0,0,0,0.2);
            border-radius: 12px;
            padding: 10px;
            text-align: center;
            margin-top: 30px;
        }

        /* 로딩 */
        .loading {
            text-align: center;
            padding: 40px;
            color: rgba(255,255,255,0.5);
        }

        /* 반응형 */
        @media (max-width: 768px) {
            .container {
                padding: 12px;
            }

            .community-header {
                flex-direction: column;
                align-items: flex-start;
                gap: 12px;
                padding: 16px 0;
            }

            .header-left {
                width: 100%;
                flex-direction: column;
                align-items: flex-start;
                gap: 8px;
            }

            .page-title {
                font-size: 18px;
                white-space: nowrap;
            }

            .back-btn {
                padding: 8px 12px;
                font-size: 13px;
            }

            .theme-toggle {
                position: absolute;
                top: 20px;
                right: 12px;
            }

            .category-tabs {
                gap: 8px;
                padding-bottom: 8px;
            }

            .category-tab {
                padding: 8px 14px;
                font-size: 12px;
            }

            .form-row {
                flex-direction: column;
            }

            .form-select {
                width: 100%;
            }

            .form-input, .form-textarea {
                font-size: 14px;
            }

            .write-header {
                padding: 14px 16px;
            }

            .write-header-title {
                font-size: 14px;
            }

            .post-item {
                padding: 14px;
            }

            .post-title {
                font-size: 14px;
            }

            .post-content {
                font-size: 13px;
            }

            .post-meta {
                font-size: 11px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- 헤더 -->
        <div class="community-header">
            <div class="header-left">
                <a href="/" class="back-btn">← 분석기</a>
                <div class="page-title">💬 블로거 커뮤니티</div>
            </div>
            <button class="theme-toggle" onclick="toggleTheme()" title="테마 전환">🌙</button>
        </div>

        <!-- 상단 배너 광고 -->
        <div class="ad-banner-top">
            <div class="ad-label">광고</div>
            <ins class="kakao_ad_area" style="display:none;"
            data-ad-unit = "DAN-swwvk4Kp8cMpG1FI"
            data-ad-width = "320"
            data-ad-height = "100"></ins>
        </div>

        <!-- 카테고리 탭 -->
        <div class="category-tabs">
            <button class="category-tab active" onclick="switchTab('all', this)">전체</button>
            <button class="category-tab" onclick="switchTab('question', this)">❓ 질문</button>
            <button class="category-tab" onclick="switchTab('info', this)">📢 정보공유</button>
            <button class="category-tab" onclick="switchTab('diary', this)">📝 성장일기</button>
        </div>

        <!-- 글쓰기 섹션 -->
        <div class="write-section">
            <div class="write-header" onclick="toggleWriteForm()">
                <span class="write-header-title">✏️ 새 글 작성하기</span>
                <span class="write-arrow">▼</span>
            </div>
            <div class="write-form" id="writeForm">
                <div class="form-row">
                    <input type="text" class="form-input" id="inputNickname" placeholder="닉네임 (익명 가능)" maxlength="20">
                    <select class="form-select" id="inputCategory">
                        <option value="question">질문</option>
                        <option value="info">정보공유</option>
                        <option value="diary">성장일기</option>
                    </select>
                </div>
                <input type="text" class="form-input" id="inputTitle" placeholder="제목을 입력하세요" maxlength="100" style="width:100%; margin-bottom:12px;">
                <textarea class="form-textarea" id="inputContent" placeholder="내용을 입력하세요"></textarea>
                <button class="submit-btn" onclick="submitPost()">작성하기</button>
            </div>
        </div>

        <!-- 글쓰기 아래 광고 -->
        <div class="ad-after-write">
            <div class="ad-label">광고</div>
            <ins class="kakao_ad_area" style="display:none;"
            data-ad-unit = "DAN-qYU1Nbac9rUaGFpF"
            data-ad-width = "320"
            data-ad-height = "100"></ins>
        </div>

        <!-- 게시글 목록 -->
        <div class="posts-list" id="postsList">
            <div class="loading">게시글을 불러오는 중...</div>
        </div>

        <!-- 페이지네이션 -->
        <div class="pagination" id="pagination"></div>

        <!-- 하단 광고 -->
        <div class="ad-bottom">
            <div class="ad-label">광고</div>
            <ins class="kakao_ad_area" style="display:none;"
            data-ad-unit = "DAN-swwvk4Kp8cMpG1FI"
            data-ad-width = "320"
            data-ad-height = "100"></ins>
        </div>
    </div>

    <script>
        let currentTab = 'all';
        let currentPage = 1;
        const postsPerPage = 10;

        // 테마 관리
        const THEME_KEY = 'blog_analyzer_theme';

        function toggleTheme() {
            const body = document.body;
            const btn = document.querySelector('.theme-toggle');

            if (body.classList.contains('light-mode')) {
                body.classList.remove('light-mode');
                btn.textContent = '🌙';
                localStorage.setItem(THEME_KEY, 'dark');
            } else {
                body.classList.add('light-mode');
                btn.textContent = '☀️';
                localStorage.setItem(THEME_KEY, 'light');
            }
        }

        function loadTheme() {
            const saved = localStorage.getItem(THEME_KEY);
            const btn = document.querySelector('.theme-toggle');
            if (saved === 'light') {
                document.body.classList.add('light-mode');
                if (btn) btn.textContent = '☀️';
            }
        }

        // 글쓰기 폼 토글
        function toggleWriteForm() {
            const form = document.getElementById('writeForm');
            const arrow = document.querySelector('.write-arrow');
            form.classList.toggle('active');
            arrow.style.transform = form.classList.contains('active') ? 'rotate(180deg)' : 'rotate(0deg)';
        }

        // 탭 전환
        function switchTab(tab, btn) {
            currentTab = tab;
            currentPage = 1;

            document.querySelectorAll('.category-tab').forEach(t => t.classList.remove('active'));
            btn.classList.add('active');

            loadPosts();
        }

        // 게시글 로드
        async function loadPosts() {
            const container = document.getElementById('postsList');
            container.innerHTML = '<div class="loading">게시글을 불러오는 중...</div>';

            try {
                let url = '/api/community/posts?page=' + currentPage + '&limit=' + postsPerPage;
                if (currentTab !== 'all') {
                    url += '&category=' + currentTab;
                }

                const response = await fetch(url);
                const data = await response.json();

                if (data.posts && data.posts.length > 0) {
                    const categoryNames = {
                        'question': '질문',
                        'info': '정보공유',
                        'diary': '성장일기'
                    };

                    let html = '';
                    data.posts.forEach((post, index) => {
                        html += `
                            <div class="post-card" onclick="viewPost(${post.id})">
                                <span class="post-category-badge ${post.category}">${categoryNames[post.category] || post.category}</span>
                                <div class="post-title">${escapeHtml(post.title)}</div>
                                <div class="post-meta">
                                    <span>${post.nickname || '익명'}</span>
                                    <span>${formatDate(post.created_at)}</span>
                                    <div class="post-stats">
                                        <span>👍 ${post.likes || 0}</span>
                                        <span>💬 ${post.comments || 0}</span>
                                    </div>
                                </div>
                            </div>
                        `;

                        // 5개마다 광고 삽입
                        if ((index + 1) % 5 === 0 && index < data.posts.length - 1) {
                            html += `
                                <div class="ad-in-list">
                                    <div class="ad-label">광고</div>
                                    <ins class="kakao_ad_area" style="display:none;"
                                    data-ad-unit = "DAN-qYU1Nbac9rUaGFpF"
                                    data-ad-width = "320"
                                    data-ad-height = "100"></ins>
                                </div>
                            `;
                        }
                    });

                    container.innerHTML = html;
                    renderPagination(data.total);

                    // 광고 다시 로드
                    if (window.kakaoAdFit) {
                        kakaoAdFit.load();
                    }
                } else {
                    container.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-icon">📝</div>
                            <p>아직 게시글이 없습니다.</p>
                            <p style="font-size: 13px; margin-top: 8px;">첫 번째 글을 작성해보세요!</p>
                        </div>
                    `;
                    document.getElementById('pagination').innerHTML = '';
                }
            } catch (error) {
                console.error('Load posts error:', error);
                container.innerHTML = '<div class="empty-state">게시글을 불러올 수 없습니다.</div>';
            }
        }

        // 페이지네이션
        function renderPagination(total) {
            const container = document.getElementById('pagination');
            const totalPages = Math.ceil(total / postsPerPage);

            if (totalPages <= 1) {
                container.innerHTML = '';
                return;
            }

            let html = '';
            for (let i = 1; i <= totalPages; i++) {
                html += `<button class="page-btn ${i === currentPage ? 'active' : ''}" onclick="goToPage(${i})">${i}</button>`;
            }
            container.innerHTML = html;
        }

        function goToPage(page) {
            currentPage = page;
            loadPosts();
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }

        // 글 작성
        async function submitPost() {
            const nickname = document.getElementById('inputNickname').value.trim() || '익명';
            const category = document.getElementById('inputCategory').value;
            const title = document.getElementById('inputTitle').value.trim();
            const content = document.getElementById('inputContent').value.trim();

            if (!title) {
                alert('제목을 입력해주세요.');
                return;
            }
            if (!content) {
                alert('내용을 입력해주세요.');
                return;
            }

            try {
                const response = await fetch('/api/community/posts', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ nickname, category, title, content })
                });

                const data = await response.json();

                if (data.success) {
                    alert('게시글이 작성되었습니다!');
                    document.getElementById('inputNickname').value = '';
                    document.getElementById('inputTitle').value = '';
                    document.getElementById('inputContent').value = '';
                    toggleWriteForm();
                    loadPosts();
                } else {
                    alert(data.error || '게시글 작성에 실패했습니다.');
                }
            } catch (error) {
                console.error('Submit error:', error);
                alert('게시글 작성 중 오류가 발생했습니다.');
            }
        }

        // 글 보기
        function viewPost(postId) {
            alert('게시글 상세 보기 기능은 준비 중입니다.');
        }

        // 유틸리티
        function formatDate(dateStr) {
            const date = new Date(dateStr);
            const now = new Date();
            const diff = now - date;

            if (diff < 60000) return '방금 전';
            if (diff < 3600000) return Math.floor(diff / 60000) + '분 전';
            if (diff < 86400000) return Math.floor(diff / 3600000) + '시간 전';
            if (diff < 604800000) return Math.floor(diff / 86400000) + '일 전';

            return date.toLocaleDateString('ko-KR');
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // 초기화
        document.addEventListener('DOMContentLoaded', function() {
            loadTheme();
            loadPosts();
        });
    </script>
</body>
</html>'''


# ads.txt (광고 인증)
@app.route('/ads.txt')
def ads_txt():
    """ads.txt for ad verification"""
    content = """google.com, pub-3955152413866694, DIRECT, f08c47fec0942fa0
kakao.com, pub-4939783373620498, DIRECT"""
    return content, 200, {'Content-Type': 'text/plain; charset=utf-8'}


@app.route('/google14d6946e204296a4.html')
def google_verification():
    """Google Search Console verification"""
    return 'google-site-verification: google14d6946e204296a4.html', 200, {'Content-Type': 'text/html; charset=utf-8'}


@app.route('/sitemap.xml')
def sitemap():
    """Sitemap for search engines"""
    sitemap_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://blog-analyzer-aafw.onrender.com/</loc>
    <lastmod>2026-01-02</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>https://blog-analyzer-aafw.onrender.com/community</loc>
    <lastmod>2026-01-02</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>
</urlset>'''
    return sitemap_xml, 200, {'Content-Type': 'application/xml; charset=utf-8'}


@app.route('/robots.txt')
def robots():
    """Robots.txt for search engines"""
    robots_txt = '''User-agent: *
Allow: /

Sitemap: https://blog-analyzer-aafw.onrender.com/sitemap.xml'''
    return robots_txt, 200, {'Content-Type': 'text/plain; charset=utf-8'}


# HTML 페이지 (프론트엔드)
@app.route('/')
def index():
    """메인 페이지"""
    return '''
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>블로그 지수 분석기</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📊</text></svg>">
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-3955152413866694" crossorigin="anonymous"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Noto Sans KR', sans-serif;
            background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #16213e 100%);
            min-height: 100vh;
            color: #fff;
        }
        
        .container {
            max-width: 1000px;
            margin: 0 auto;
            padding: 40px 20px;
        }
        
        header {
            text-align: center;
            margin-bottom: 40px;
        }

        .header-badges {
            display: flex;
            justify-content: center;
            gap: 12px;
            flex-wrap: wrap;
        }

        .header-badge {
            background: rgba(102, 126, 234, 0.15);
            border: 1px solid rgba(102, 126, 234, 0.3);
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 12px;
            color: rgba(255,255,255,0.8);
        }

        .logo {
            display: inline-flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 16px;
        }
        
        .logo-icon {
            width: 50px;
            height: 50px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 14px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
        }
        
        h1 {
            font-size: 28px;
            font-weight: 700;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 50%, #f093fb 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .subtitle {
            color: rgba(255,255,255,0.5);
            font-size: 14px;
            margin-top: 8px;
        }
        
        .search-box {
            background: rgba(255,255,255,0.05);
            border-radius: 20px;
            padding: 32px;
            border: 1px solid rgba(255,255,255,0.1);
            margin-bottom: 32px;
        }
        
        .search-form {
            display: flex;
            gap: 12px;
        }
        
        .input-wrapper {
            flex: 1;
            display: flex;
            align-items: center;
            background: rgba(255,255,255,0.08);
            border-radius: 12px;
            padding: 4px 4px 4px 16px;
            border: 2px solid rgba(102, 126, 234, 0.3);
        }
        
        .input-prefix, .input-suffix {
            color: rgba(255,255,255,0.4);
            font-size: 14px;
            white-space: nowrap;
        }

        .input-suffix {
            margin-left: -8px;
        }

        input[type="text"] {
            flex: 1;
            background: transparent;
            border: none;
            outline: none;
            color: #fff;
            font-size: 16px;
            padding: 14px 12px;
        }
        
        input::placeholder {
            color: rgba(255,255,255,0.3);
        }
        
        .search-btn {
            padding: 0 28px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border: none;
            border-radius: 12px;
            color: #fff;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
            box-shadow: 0 4px 20px rgba(102, 126, 234, 0.4);
        }
        
        .search-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 25px rgba(102, 126, 234, 0.5);
        }
        
        .search-btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        
        .loading {
            text-align: center;
            padding: 60px 20px;
        }
        
        .spinner {
            width: 50px;
            height: 50px;
            border: 3px solid rgba(255,255,255,0.1);
            border-top-color: #667eea;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 20px;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        .error {
            background: rgba(255, 107, 107, 0.1);
            border: 1px solid rgba(255, 107, 107, 0.3);
            border-radius: 12px;
            padding: 16px;
            color: #ff6b6b;
            text-align: center;
            margin-bottom: 20px;
        }
        
        .result {
            animation: fadeIn 0.5s ease;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .profile-card {
            background: rgba(255,255,255,0.05);
            border-radius: 20px;
            padding: 28px;
            border: 1px solid rgba(255,255,255,0.1);
            display: grid;
            grid-template-columns: auto 1fr auto;
            gap: 28px;
            align-items: center;
            margin-bottom: 24px;
        }
        
        .profile-image {
            width: 90px;
            height: 90px;
            border-radius: 50%;
            background-size: cover;
            background-position: center;
            border: 4px solid;
        }
        
        .profile-info h2 {
            font-size: 22px;
            margin-bottom: 6px;
        }
        
        .profile-info .blog-id {
            color: rgba(255,255,255,0.5);
            font-size: 14px;
            margin-bottom: 14px;
        }

        .profile-info .blog-link {
            text-decoration: none;
            transition: all 0.3s ease;
        }

        .profile-info .blog-link:hover .blog-id {
            color: #667eea;
            text-decoration: underline;
        }
        
        .profile-meta {
            display: flex;
            gap: 20px;
            font-size: 13px;
            color: rgba(255,255,255,0.6);
        }
        
        .index-badge {
            text-align: center;
            padding: 20px 28px;
            border-radius: 16px;
            background: rgba(255,255,255,0.05);
        }
        
        .index-label {
            font-size: 13px;
            color: rgba(255,255,255,0.5);
            margin-bottom: 6px;
        }
        
        .index-grade {
            font-size: 32px;
            font-weight: 800;
        }
        
        .index-score {
            margin-top: 8px;
            padding: 4px 12px;
            background: rgba(255,255,255,0.1);
            border-radius: 10px;
            font-size: 12px;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
            margin-bottom: 24px;
        }
        
        .stat-card {
            background: rgba(255,255,255,0.05);
            border-radius: 16px;
            padding: 20px;
            text-align: center;
            border: 1px solid rgba(255,255,255,0.08);
        }
        
        .stat-icon {
            width: 44px;
            height: 44px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 10px;
            font-size: 20px;
        }
        
        .stat-value {
            font-size: 22px;
            font-weight: 700;
            margin-bottom: 4px;
        }
        
        .stat-label {
            font-size: 12px;
            color: rgba(255,255,255,0.5);
        }
        
        .section-card {
            background: rgba(255,255,255,0.05);
            border-radius: 20px;
            padding: 28px;
            border: 1px solid rgba(255,255,255,0.1);
            margin-bottom: 24px;
        }
        
        .section-title {
            font-size: 17px;
            font-weight: 600;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .progress-bar {
            height: 10px;
            background: rgba(255,255,255,0.1);
            border-radius: 5px;
            overflow: hidden;
            margin-bottom: 24px;
        }
        
        .progress-fill {
            height: 100%;
            border-radius: 5px;
            transition: width 1s ease;
        }
        
        .grade-labels {
            display: flex;
            justify-content: space-between;
            font-size: 11px;
            color: rgba(255,255,255,0.4);
        }
        
        .breakdown-grid {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 12px;
            margin-top: 24px;
        }
        
        .breakdown-item {
            background: rgba(255,255,255,0.05);
            border-radius: 10px;
            padding: 14px;
            text-align: center;
        }
        
        .breakdown-label {
            font-size: 11px;
            color: rgba(255,255,255,0.5);
            margin-bottom: 6px;
        }
        
        .breakdown-value {
            font-size: 18px;
            font-weight: 700;
            color: #667eea;
        }
        
        .breakdown-max {
            font-size: 10px;
            color: rgba(255,255,255,0.3);
        }
        
        .post-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
            max-height: 500px;
            overflow-y: auto;
            padding-right: 8px;
        }

        .post-list::-webkit-scrollbar {
            width: 6px;
        }

        .post-list::-webkit-scrollbar-track {
            background: rgba(255,255,255,0.05);
            border-radius: 3px;
        }

        .post-list::-webkit-scrollbar-thumb {
            background: rgba(102, 126, 234, 0.5);
            border-radius: 3px;
        }

        .post-list::-webkit-scrollbar-thumb:hover {
            background: rgba(102, 126, 234, 0.7);
        }

        /* 포스팅 지수 테이블 스타일 */
        .post-index-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }

        .post-index-table thead {
            background: rgba(255,255,255,0.05);
            position: sticky;
            top: 0;
        }

        .post-index-table th {
            padding: 12px 10px;
            text-align: left;
            font-weight: 600;
            color: rgba(255,255,255,0.7);
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }

        .post-index-table td {
            padding: 12px 10px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            vertical-align: middle;
        }

        .post-index-table tbody tr:hover {
            background: rgba(255,255,255,0.03);
        }

        /* 숨김 포스트 행 */
        .hidden-post-row {
            display: none;
        }

        .hidden-post-row.show {
            display: table-row;
        }

        /* 더보기 버튼 */
        .load-more-container {
            text-align: center;
            padding: 16px 0;
            margin-top: 8px;
        }

        .load-more-btn {
            background: linear-gradient(135deg, rgba(102, 126, 234, 0.2), rgba(118, 75, 162, 0.2));
            border: 1px solid rgba(102, 126, 234, 0.4);
            color: #667eea;
            padding: 12px 32px;
            border-radius: 25px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
        }

        .load-more-btn:hover {
            background: linear-gradient(135deg, rgba(102, 126, 234, 0.4), rgba(118, 75, 162, 0.4));
            border-color: rgba(102, 126, 234, 0.6);
            transform: translateY(-2px);
        }

        .load-more-btn.expanded {
            background: rgba(255,255,255,0.1);
            border-color: rgba(255,255,255,0.2);
            color: rgba(255,255,255,0.6);
        }

        /* 게시글 진단 테이블 스타일 */
        .post-diagnosis-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }

        .post-diagnosis-table thead {
            background: rgba(102, 126, 234, 0.1);
            position: sticky;
            top: 0;
        }

        .post-diagnosis-table th {
            padding: 14px 12px;
            text-align: left;
            font-weight: 600;
            color: rgba(255,255,255,0.8);
            border-bottom: 2px solid rgba(102, 126, 234, 0.3);
        }

        .post-diagnosis-table td {
            padding: 14px 12px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            vertical-align: middle;
        }

        .post-diagnosis-table tbody tr:hover {
            background: rgba(102, 126, 234, 0.05);
        }

        .post-diagnosis-table .post-title-link {
            max-width: 280px;
        }

        .post-title-link {
            color: #7eb8ff;
            text-decoration: none;
            font-weight: 500;
            display: block;
            max-width: 350px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .post-title-link:hover {
            text-decoration: underline;
        }

        .keyword-link {
            color: #ffd54f;
            text-decoration: none;
            font-size: 12px;
            display: block;
            max-width: 200px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .keyword-link:hover {
            text-decoration: underline;
            color: #ffeb3b;
        }

        .exposure-badge {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        }

        .exposure-indexed {
            background: rgba(76, 175, 80, 0.2);
            color: #81c784;
        }

        .exposure-pending {
            background: rgba(255, 193, 7, 0.2);
            color: #ffd54f;
        }

        .exposure-missing {
            background: rgba(244, 67, 54, 0.2);
            color: #e57373;
        }

        .post-stats {
            display: flex;
            gap: 12px;
            color: rgba(255,255,255,0.6);
            font-size: 12px;
        }

        .post-stat-item {
            display: flex;
            align-items: center;
            gap: 3px;
        }

        .table-scroll-container {
            max-height: 450px;
            overflow-y: auto;
            border-radius: 8px;
        }

        .table-scroll-container::-webkit-scrollbar {
            width: 6px;
        }

        .table-scroll-container::-webkit-scrollbar-track {
            background: rgba(255,255,255,0.05);
        }

        .table-scroll-container::-webkit-scrollbar-thumb {
            background: rgba(102, 126, 234, 0.5);
            border-radius: 3px;
        }

        .post-date-cell {
            color: rgba(255,255,255,0.5);
            font-size: 12px;
            white-space: nowrap;
        }

        /* 상세 분석 버튼 스타일 */
        .analyze-btn {
            padding: 6px 12px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border: none;
            border-radius: 6px;
            color: white;
            font-size: 11px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            white-space: nowrap;
        }

        .analyze-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
        }

        /* 형태소 키워드 링크 */
        .morpheme-keyword-link {
            display: inline-block;
            background: #667eea33;
            color: #fff;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 13px;
            margin: 4px;
            border: 1px solid #667eea4d;
            text-decoration: none;
            transition: all 0.2s;
            cursor: pointer;
        }

        .morpheme-keyword-link:hover {
            background: #667eea66;
        }

        /* 모달 스타일 */
        .modal-overlay {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.8);
            z-index: 1000;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }

        .modal-overlay.active {
            display: flex;
        }

        .modal-content {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            border-radius: 16px;
            max-width: 700px;
            width: 100%;
            max-height: 85vh;
            overflow-y: auto;
            border: 1px solid rgba(102, 126, 234, 0.3);
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
        }

        .modal-header {
            padding: 20px 24px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .modal-header h3 {
            color: white;
            font-size: 18px;
            font-weight: 600;
        }

        .modal-close {
            background: rgba(255,255,255,0.1);
            border: none;
            color: white;
            width: 32px;
            height: 32px;
            border-radius: 50%;
            cursor: pointer;
            font-size: 18px;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: background 0.3s;
        }

        .modal-close:hover {
            background: rgba(244, 67, 54, 0.5);
        }

        .modal-body {
            padding: 24px;
        }

        .analysis-section {
            margin-bottom: 20px;
        }

        .analysis-section h4 {
            color: #7eb8ff;
            font-size: 14px;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .analysis-item {
            background: rgba(255,255,255,0.05);
            border-radius: 8px;
            padding: 14px;
            margin-bottom: 10px;
        }

        .analysis-label {
            color: rgba(255,255,255,0.6);
            font-size: 12px;
            margin-bottom: 6px;
        }

        .analysis-value {
            color: white;
            font-size: 14px;
        }

        .analysis-tip {
            background: linear-gradient(135deg, rgba(102, 126, 234, 0.15) 0%, rgba(118, 75, 162, 0.15) 100%);
            border-left: 3px solid #667eea;
            padding: 12px 16px;
            border-radius: 0 8px 8px 0;
            margin-top: 8px;
        }

        .analysis-tip p {
            color: rgba(255,255,255,0.85);
            font-size: 13px;
            line-height: 1.6;
        }

        .score-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 600;
        }

        .score-excellent {
            background: rgba(76, 175, 80, 0.2);
            color: #81c784;
        }

        .score-good {
            background: rgba(102, 126, 234, 0.2);
            color: #7eb8ff;
        }

        .score-average {
            background: rgba(255, 193, 7, 0.2);
            color: #ffd54f;
        }

        .score-poor {
            background: rgba(244, 67, 54, 0.2);
            color: #e57373;
        }

        /* 차트 스타일 */
        .charts-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 20px;
            margin-bottom: 24px;
        }

        .chart-card {
            background: rgba(255,255,255,0.05);
            border-radius: 16px;
            padding: 20px;
            border: 1px solid rgba(255,255,255,0.08);
        }

        .chart-title {
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 15px;
            color: rgba(255,255,255,0.9);
        }

        .chart-container {
            position: relative;
            height: 200px;
        }

        .chart-container-large {
            position: relative;
            height: 250px;
        }

        @media (max-width: 768px) {
            .charts-grid {
                grid-template-columns: 1fr;
            }
        }

        /* 블로그 코칭 스타일 */
        .coaching-section {
            background: linear-gradient(135deg, rgba(102, 126, 234, 0.1), rgba(118, 75, 162, 0.1));
            border: 1px solid rgba(102, 126, 234, 0.3);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 24px;
        }

        .coaching-header {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 20px;
        }

        .coaching-icon {
            font-size: 32px;
        }

        .coaching-title {
            font-size: 18px;
            font-weight: 700;
            color: #fff;
        }

        .coaching-subtitle {
            font-size: 12px;
            color: rgba(255,255,255,0.5);
        }

        .diagnosis-box {
            background: rgba(0,0,0,0.2);
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 20px;
        }

        .diagnosis-title {
            font-size: 14px;
            font-weight: 600;
            color: #ffd54f;
            margin-bottom: 10px;
        }

        .diagnosis-content {
            font-size: 13px;
            line-height: 1.7;
            color: rgba(255,255,255,0.85);
        }

        .advice-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 16px;
        }

        @media (max-width: 768px) {
            .advice-grid {
                grid-template-columns: 1fr;
            }
        }

        .advice-card {
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            padding: 16px;
            border: 1px solid rgba(255,255,255,0.08);
        }

        .advice-card-header {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 12px;
        }

        .advice-card-icon {
            font-size: 20px;
        }

        .advice-card-title {
            font-size: 14px;
            font-weight: 600;
            color: #7eb8ff;
        }

        .advice-card-content {
            font-size: 12px;
            line-height: 1.6;
            color: rgba(255,255,255,0.75);
        }

        .advice-card-content ul {
            margin: 8px 0;
            padding-left: 16px;
        }

        .advice-card-content li {
            margin-bottom: 4px;
        }

        .highlight {
            color: #ffd54f;
            font-weight: 600;
        }

        .good {
            color: #81c784;
        }

        .bad {
            color: #e57373;
        }

        .tip-box {
            background: rgba(255, 193, 7, 0.1);
            border: 1px solid rgba(255, 193, 7, 0.3);
            border-radius: 8px;
            padding: 12px;
            margin-top: 8px;
            font-size: 11px;
            color: #ffd54f;
        }

        /* 아코디언 스타일 */
        .accordion-item {
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            margin-bottom: 12px;
            border: 1px solid rgba(255,255,255,0.08);
            overflow: hidden;
        }

        .accordion-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 16px 20px;
            cursor: pointer;
            transition: background 0.3s;
        }

        .accordion-header:hover {
            background: rgba(255,255,255,0.05);
        }

        .accordion-header-content {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .accordion-icon {
            font-size: 20px;
        }

        .accordion-title {
            font-size: 14px;
            font-weight: 600;
            color: #7eb8ff;
        }

        .accordion-arrow {
            font-size: 14px;
            color: rgba(255,255,255,0.5);
            transition: transform 0.3s;
        }

        .accordion-item.open .accordion-arrow {
            transform: rotate(180deg);
        }

        .accordion-body {
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease-out;
        }

        .accordion-item.open .accordion-body {
            max-height: 2000px;
        }

        .accordion-content {
            padding: 0 20px 20px 20px;
        }

        /* 진단 섹션 좋은점/나쁜점 스타일 */
        .diagnosis-section {
            margin-bottom: 16px;
        }

        .diagnosis-section-title {
            font-size: 13px;
            font-weight: 600;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .diagnosis-good-title {
            color: #81c784;
        }

        .diagnosis-bad-title {
            color: #e57373;
        }

        .diagnosis-list {
            list-style: none;
            padding: 0;
            margin: 0;
        }

        .diagnosis-list li {
            padding: 10px 14px;
            background: rgba(0,0,0,0.2);
            border-radius: 8px;
            margin-bottom: 8px;
            font-size: 13px;
            line-height: 1.5;
            color: rgba(255,255,255,0.85);
            display: flex;
            align-items: flex-start;
            gap: 10px;
        }

        .diagnosis-list li::before {
            content: '';
            width: 6px;
            height: 6px;
            border-radius: 50%;
            margin-top: 6px;
            flex-shrink: 0;
        }

        .diagnosis-good-list li::before {
            background: #81c784;
        }

        .diagnosis-bad-list li::before {
            background: #e57373;
        }

        /* 다음 등급까지 섹션 */
        .next-grade-section {
            margin-top: 20px;
        }

        .next-grade-box {
            background: linear-gradient(135deg, rgba(240, 147, 251, 0.1) 0%, rgba(102, 126, 234, 0.1) 100%);
            border: 1px solid rgba(240, 147, 251, 0.3);
            border-radius: 12px;
            padding: 20px;
        }

        .next-grade-progress {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 16px;
        }

        .current-grade, .next-grade {
            font-size: 18px;
            font-weight: 700;
            min-width: 50px;
            text-align: center;
        }

        .progress-bar {
            flex: 1;
            height: 10px;
            background: rgba(255,255,255,0.1);
            border-radius: 5px;
            overflow: hidden;
        }

        .progress-fill {
            height: 100%;
            border-radius: 5px;
            transition: width 0.5s ease;
        }

        .next-grade-need {
            text-align: center;
            font-size: 14px;
            color: rgba(255,255,255,0.8);
            margin-bottom: 16px;
        }

        .next-grade-need strong {
            color: #f093fb;
            font-size: 18px;
        }

        .next-grade-tips {
            list-style: none;
            padding: 0;
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            justify-content: center;
        }

        .next-grade-tips li {
            background: rgba(255,255,255,0.1);
            padding: 6px 14px;
            border-radius: 16px;
            font-size: 12px;
            color: rgba(255,255,255,0.8);
        }

        /* 키워드 경쟁도 뱃지 */
        .competition-badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 10px;
            font-weight: 600;
            margin-left: 6px;
        }

        .competition-low {
            background: rgba(0, 200, 83, 0.2);
            color: #00C853;
        }

        .competition-medium {
            background: rgba(255, 193, 7, 0.2);
            color: #FFC107;
        }

        .competition-high {
            background: rgba(244, 67, 54, 0.2);
            color: #F44336;
        }

        .post-item {
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 16px;
            padding: 14px 18px;
            background: rgba(255,255,255,0.03);
            border-radius: 10px;
            border: 1px solid rgba(255,255,255,0.05);
        }
        
        .post-title {
            font-weight: 500;
            margin-bottom: 4px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        
        .post-date {
            font-size: 12px;
            color: rgba(255,255,255,0.4);
        }
        
        .post-link {
            color: #667eea;
            text-decoration: none;
            font-size: 13px;
            white-space: nowrap;
        }
        
        .post-link:hover {
            text-decoration: underline;
        }
        
        .info-box {
            background: rgba(102, 126, 234, 0.1);
            border: 1px solid rgba(102, 126, 234, 0.2);
            border-radius: 12px;
            padding: 18px;
            font-size: 13px;
            color: rgba(255,255,255,0.7);
            line-height: 1.7;
        }
        
        @media (max-width: 768px) {
            .profile-card {
                grid-template-columns: 1fr;
                text-align: center;
            }

            .profile-image {
                margin: 0 auto;
            }

            .profile-meta {
                justify-content: center;
            }

            .stats-grid {
                grid-template-columns: repeat(2, 1fr);
            }

            .breakdown-grid {
                grid-template-columns: repeat(3, 1fr);
            }

            .search-form {
                flex-direction: column;
            }
        }

        /* 히스토리 섹션 스타일 */
        .history-section {
            background: rgba(255,255,255,0.03);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 24px;
            border: 1px solid rgba(255,255,255,0.08);
        }

        .history-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }

        .history-title {
            font-size: 14px;
            font-weight: 600;
            color: rgba(255,255,255,0.8);
        }

        .history-clear-btn {
            background: transparent;
            border: 1px solid rgba(255,255,255,0.2);
            color: rgba(255,255,255,0.5);
            padding: 6px 12px;
            border-radius: 8px;
            font-size: 11px;
            cursor: pointer;
            transition: all 0.2s;
        }

        .history-clear-btn:hover {
            background: rgba(255,255,255,0.1);
            color: rgba(255,255,255,0.8);
        }

        .history-list {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }

        .history-item {
            display: flex;
            align-items: center;
            gap: 8px;
            background: rgba(102, 126, 234, 0.15);
            padding: 8px 14px;
            border-radius: 20px;
            cursor: pointer;
            transition: all 0.2s;
            border: 1px solid rgba(102, 126, 234, 0.3);
        }

        .history-item:hover {
            background: rgba(102, 126, 234, 0.25);
            transform: translateY(-1px);
        }

        .history-item-name {
            font-size: 13px;
            color: #fff;
            max-width: 120px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .history-item-grade {
            font-size: 11px;
            font-weight: 600;
            padding: 2px 8px;
            border-radius: 10px;
        }

        .history-item-date {
            font-size: 10px;
            color: rgba(255,255,255,0.4);
        }

        .history-item-delete {
            color: rgba(255,255,255,0.3);
            font-size: 14px;
            line-height: 1;
            cursor: pointer;
            padding: 2px;
        }

        .history-item-delete:hover {
            color: #ff6b6b;
        }

        /* 키워드 추천 스타일 */
        .keyword-suggest-box {
            position: relative;
            margin-top: 16px;
        }

        .keyword-input-wrapper {
            display: flex;
            gap: 10px;
        }

        .keyword-input {
            flex: 1;
            background: rgba(255,255,255,0.08);
            border: 2px solid rgba(102, 126, 234, 0.3);
            border-radius: 10px;
            padding: 12px 16px;
            color: #fff;
            font-size: 14px;
            outline: none;
        }

        .keyword-input:focus {
            border-color: rgba(102, 126, 234, 0.6);
        }

        .keyword-suggest-btn {
            padding: 12px 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border: none;
            border-radius: 10px;
            color: #fff;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            white-space: nowrap;
        }

        .suggest-results {
            margin-top: 12px;
            display: none;
        }

        .suggest-results.show {
            display: block;
        }

        .suggest-label {
            font-size: 12px;
            color: rgba(255,255,255,0.5);
            margin-bottom: 8px;
        }

        .suggest-tags {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }

        .suggest-tag {
            background: rgba(255,255,255,0.08);
            padding: 8px 14px;
            border-radius: 20px;
            font-size: 13px;
            color: rgba(255,255,255,0.85);
            cursor: pointer;
            transition: all 0.2s;
            border: 1px solid rgba(255,255,255,0.1);
        }

        .suggest-tag:hover {
            background: rgba(102, 126, 234, 0.2);
            border-color: rgba(102, 126, 234, 0.4);
        }

        /* 푸터 스타일 */
        .footer {
            margin-top: 60px;
            padding: 30px 0;
            border-top: 1px solid rgba(255,255,255,0.1);
            text-align: center;
        }

        .footer-disclaimer {
            background: rgba(255,255,255,0.03);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            text-align: left;
        }

        .footer-disclaimer h4 {
            font-size: 13px;
            color: rgba(255,255,255,0.7);
            margin-bottom: 12px;
        }

        .footer-disclaimer ul {
            list-style: none;
            font-size: 11px;
            color: rgba(255,255,255,0.5);
            line-height: 1.8;
        }

        .footer-disclaimer li {
            padding-left: 16px;
            position: relative;
        }

        .footer-disclaimer li::before {
            content: "•";
            position: absolute;
            left: 0;
            color: rgba(102, 126, 234, 0.6);
        }

        .footer-links {
            display: flex;
            justify-content: center;
            gap: 20px;
            margin-bottom: 16px;
        }

        .footer-links a {
            color: rgba(255,255,255,0.5);
            text-decoration: none;
            font-size: 12px;
            transition: color 0.2s;
        }

        .footer-links a:hover {
            color: #667eea;
        }

        .footer-copyright {
            font-size: 11px;
            color: rgba(255,255,255,0.3);
        }

        .footer-copyright a {
            color: rgba(102, 126, 234, 0.7);
            text-decoration: none;
        }

        /* 다크/라이트 모드 전환 */
        .theme-toggle {
            position: fixed;
            top: 20px;
            right: 20px;
            background: rgba(255,255,255,0.1);
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 50%;
            width: 48px;
            height: 48px;
            cursor: pointer;
            font-size: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
            transition: all 0.3s;
        }

        .theme-toggle:hover {
            background: rgba(255,255,255,0.2);
            transform: scale(1.1);
        }

        /* 라이트 모드 스타일 */
        body.light-mode {
            background: linear-gradient(135deg, #f5f7fa 0%, #e4e8ec 50%, #d9dfe5 100%);
            color: #333;
        }

        body.light-mode .search-box,
        body.light-mode .section-card,
        body.light-mode .stat-card,
        body.light-mode .chart-card,
        body.light-mode .coaching-section,
        body.light-mode .history-section {
            background: rgba(255,255,255,0.9);
            border-color: rgba(0,0,0,0.1);
        }

        body.light-mode .profile-card {
            background: rgba(255,255,255,0.95);
            border-color: rgba(0,0,0,0.1);
        }

        body.light-mode h1 {
            background: linear-gradient(90deg, #667eea 0%, #764ba2 50%, #f093fb 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        body.light-mode .subtitle,
        body.light-mode .stat-label,
        body.light-mode .breakdown-label,
        body.light-mode .grade-labels span,
        body.light-mode .post-date,
        body.light-mode .suggest-label {
            color: rgba(0,0,0,0.5);
        }

        body.light-mode .profile-info h2,
        body.light-mode .section-title,
        body.light-mode .stat-value,
        body.light-mode .coaching-title {
            color: #333;
        }

        body.light-mode .input-wrapper {
            background: rgba(0,0,0,0.05);
            border-color: rgba(102, 126, 234, 0.5);
        }

        body.light-mode input[type="text"],
        body.light-mode .keyword-input {
            color: #333;
        }

        body.light-mode input::placeholder {
            color: rgba(0,0,0,0.4);
        }

        body.light-mode .theme-toggle {
            background: rgba(0,0,0,0.1);
            border-color: rgba(0,0,0,0.2);
        }

        body.light-mode .post-title-link {
            color: #4a6fa5;
        }

        body.light-mode .diagnosis-list li,
        body.light-mode .advice-card-content,
        body.light-mode .diagnosis-content {
            color: rgba(0,0,0,0.75);
        }

        body.light-mode .footer-disclaimer {
            background: rgba(0,0,0,0.03);
        }

        body.light-mode .footer-disclaimer h4,
        body.light-mode .footer-disclaimer li {
            color: rgba(0,0,0,0.6);
        }

        /* 트렌드 키워드 섹션 */
        .trends-section {
            background: rgba(255,255,255,0.05);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 24px;
            border: 1px solid rgba(255,255,255,0.08);
        }

        .trends-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }

        .trends-title {
            font-size: 14px;
            font-weight: 600;
            color: rgba(255,255,255,0.8);
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .trends-source {
            font-size: 10px;
            padding: 3px 8px;
            border-radius: 10px;
            font-weight: 500;
            margin-left: 8px;
        }

        .trends-source.google {
            background: linear-gradient(135deg, #4285f4, #34a853);
            color: white;
        }

        .trends-source.naver {
            background: linear-gradient(135deg, #03c75a, #00b843);
            color: white;
        }

        .trends-source.default {
            background: rgba(255,255,255,0.1);
            color: rgba(255,255,255,0.5);
        }

        .trends-refresh-btn {
            background: transparent;
            border: 1px solid rgba(255,255,255,0.2);
            color: rgba(255,255,255,0.5);
            padding: 6px 12px;
            border-radius: 8px;
            font-size: 11px;
            cursor: pointer;
            transition: all 0.2s;
        }

        .trends-refresh-btn:hover {
            background: rgba(255,255,255,0.1);
            color: rgba(255,255,255,0.8);
        }

        .trends-list {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }

        .trend-item {
            display: flex;
            align-items: center;
            gap: 8px;
            background: linear-gradient(135deg, rgba(240, 147, 251, 0.15) 0%, rgba(102, 126, 234, 0.15) 100%);
            padding: 8px 14px;
            border-radius: 20px;
            cursor: pointer;
            transition: all 0.2s;
            border: 1px solid rgba(240, 147, 251, 0.3);
        }

        .trend-item:hover {
            background: linear-gradient(135deg, rgba(240, 147, 251, 0.25) 0%, rgba(102, 126, 234, 0.25) 100%);
            transform: translateY(-1px);
        }

        .trend-rank {
            font-size: 11px;
            font-weight: 700;
            color: #667eea;
            min-width: 18px;
            text-align: center;
        }

        .trend-keyword {
            font-size: 13px;
            color: #fff;
            flex: 1;
        }

        .trend-category {
            font-size: 10px;
            background: rgba(255,255,255,0.15);
            padding: 2px 8px;
            border-radius: 10px;
            color: rgba(255,255,255,0.7);
        }

        /* SEO 점수 카드 */
        .seo-score-card {
            background: linear-gradient(135deg, rgba(102, 126, 234, 0.15) 0%, rgba(0, 200, 83, 0.15) 100%);
            border: 1px solid rgba(102, 126, 234, 0.3);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 24px;
        }

        .seo-score-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }

        .seo-score-title {
            font-size: 16px;
            font-weight: 600;
        }

        .seo-total-score {
            font-size: 28px;
            font-weight: 800;
        }

        .seo-breakdown {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
        }

        .seo-item {
            background: rgba(255,255,255,0.05);
            border-radius: 10px;
            padding: 12px;
            text-align: center;
        }

        .seo-item-label {
            font-size: 11px;
            color: rgba(255,255,255,0.5);
            margin-bottom: 4px;
        }

        .seo-item-value {
            font-size: 18px;
            font-weight: 700;
            color: #667eea;
        }

        .seo-recommendations {
            margin-top: 16px;
            padding-top: 16px;
            border-top: 1px solid rgba(255,255,255,0.1);
        }

        .seo-rec-item {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 12px;
            color: rgba(255,255,255,0.7);
            margin-bottom: 6px;
        }

        /* 히스토리 비교 모달 */
        .compare-btn {
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            border: none;
            color: white;
            padding: 6px 12px;
            border-radius: 8px;
            font-size: 11px;
            cursor: pointer;
            margin-left: 8px;
        }

        .compare-btn:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 15px rgba(240, 147, 251, 0.4);
        }

        .compare-result {
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            padding: 16px;
            margin-top: 16px;
        }

        .compare-row {
            display: grid;
            grid-template-columns: 1fr auto auto auto;
            gap: 16px;
            padding: 8px 0;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            font-size: 13px;
        }

        .compare-row:last-child {
            border-bottom: none;
        }

        .compare-label {
            color: rgba(255,255,255,0.6);
        }

        .compare-old {
            color: rgba(255,255,255,0.5);
        }

        .compare-new {
            color: #fff;
            font-weight: 600;
        }

        .compare-diff {
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 10px;
        }

        .compare-diff.positive {
            background: rgba(0, 200, 83, 0.2);
            color: #00C853;
        }

        .compare-diff.negative {
            background: rgba(244, 67, 54, 0.2);
            color: #F44336;
        }

        .compare-diff.neutral {
            background: rgba(255, 255, 255, 0.1);
            color: rgba(255,255,255,0.5);
        }

        /* PDF 다운로드 버튼 */
        .pdf-download-btn {
            background: linear-gradient(135deg, #FF6B6B 0%, #FF8E53 100%);
            border: none;
            color: white;
            padding: 12px 24px;
            border-radius: 12px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 8px;
            transition: all 0.3s;
        }

        .pdf-download-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(255, 107, 107, 0.4);
        }

        .action-buttons {
            display: flex;
            gap: 12px;
            justify-content: center;
            margin-top: 24px;
        }

        /* 경쟁 분석 섹션 */
        .competitor-section {
            background: rgba(255,255,255,0.05);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 24px;
            border: 1px solid rgba(255,255,255,0.08);
        }

        .competitor-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .competitor-item {
            display: grid;
            grid-template-columns: 40px 1fr auto;
            gap: 16px;
            align-items: center;
            padding: 12px 16px;
            background: rgba(255,255,255,0.03);
            border-radius: 10px;
            border: 1px solid rgba(255,255,255,0.05);
        }

        .competitor-item.is-mine {
            background: linear-gradient(135deg, rgba(0, 200, 83, 0.15) 0%, rgba(102, 126, 234, 0.15) 100%);
            border-color: rgba(0, 200, 83, 0.3);
        }

        .competitor-rank {
            font-size: 18px;
            font-weight: 700;
            color: #667eea;
            text-align: center;
        }

        .competitor-item.is-mine .competitor-rank {
            color: #00C853;
        }

        .competitor-info {
            overflow: hidden;
        }

        .competitor-title {
            font-size: 13px;
            color: #fff;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            margin-bottom: 4px;
        }

        .competitor-id {
            font-size: 11px;
            color: rgba(255,255,255,0.5);
        }

        .competitor-link {
            color: #7eb8ff;
            text-decoration: none;
            font-size: 12px;
        }

        .competitor-link:hover {
            text-decoration: underline;
        }

        @media (max-width: 768px) {
            .seo-breakdown {
                grid-template-columns: repeat(2, 1fr);
            }

            .action-buttons {
                flex-direction: column;
            }

            .theme-toggle {
                top: 10px;
                right: 10px;
                width: 40px;
                height: 40px;
                font-size: 16px;
            }
        }

        /* ===== 카카오 애드핏 광고 스타일 ===== */

        /* 사이드바 광고 (160x600) - PC에서만 표시 */
        .ad-sidebar {
            position: fixed;
            top: 50%;
            transform: translateY(-50%);
            z-index: 100;
        }

        .ad-sidebar-left {
            left: 20px;
        }

        .ad-sidebar-right {
            right: 20px;
        }

        .ad-sidebar-container {
            background: rgba(255, 255, 255, 0.03);
            border-radius: 12px;
            padding: 10px;
            border: 1px solid rgba(255, 255, 255, 0.08);
        }

        .ad-sidebar-label {
            font-size: 10px;
            color: rgba(255, 255, 255, 0.3);
            text-align: center;
            margin-bottom: 8px;
        }

        /* 콘텐츠 내 광고 (250x250, 300x250) */
        .ad-content-wrapper {
            display: flex;
            justify-content: center;
            align-items: center;
            margin: 24px 0;
            padding: 16px;
            background: rgba(255, 255, 255, 0.02);
            border-radius: 16px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }

        .ad-content-container {
            text-align: center;
        }

        .ad-label {
            font-size: 10px;
            color: rgba(255, 255, 255, 0.25);
            margin-bottom: 8px;
        }

        /* 푸터 광고 */
        .ad-footer-wrapper {
            display: flex;
            justify-content: center;
            margin: 32px 0 24px 0;
            padding: 20px;
            background: rgba(255, 255, 255, 0.02);
            border-radius: 16px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }

        /* 결과 영역 사이 광고 */
        .ad-between-sections {
            margin: 20px 0;
        }

        /* 반응형: 모바일에서 사이드바 광고 숨김 */
        @media (max-width: 1400px) {
            .ad-sidebar {
                display: none;
            }
        }

        /* 반응형: 태블릿/모바일에서 일부 광고 숨김 */
        @media (max-width: 768px) {
            .ad-content-wrapper.hide-mobile {
                display: none;
            }

            .ad-between-sections {
                margin: 16px 0;
            }
        }

        /* 컨테이너 최대 너비 조정 (사이드바 광고 공간 확보) */
        @media (min-width: 1400px) {
            .container {
                max-width: 1000px;
            }
        }

        /* 라이트 모드 광고 스타일 */
        .light-mode .ad-sidebar-container,
        .light-mode .ad-content-wrapper,
        .light-mode .ad-footer-wrapper {
            background: rgba(0, 0, 0, 0.02);
            border-color: rgba(0, 0, 0, 0.08);
        }

        .light-mode .ad-sidebar-label,
        .light-mode .ad-label {
            color: rgba(0, 0, 0, 0.3);
        }

        /* =====================================================
           슬라이드 메뉴 스타일
        ===================================================== */
        .hamburger-btn {
            background: none;
            border: none;
            font-size: 28px;
            cursor: pointer;
            padding: 8px 12px;
            color: #fff;
            transition: all 0.3s ease;
            border-radius: 8px;
        }

        .hamburger-btn:hover {
            background: rgba(255, 255, 255, 0.1);
        }

        .light-mode .hamburger-btn {
            color: #1a1a2e;
        }

        .light-mode .hamburger-btn:hover {
            background: rgba(0, 0, 0, 0.1);
        }

        /* 슬라이드 메뉴 오버레이 */
        .menu-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.6);
            opacity: 0;
            visibility: hidden;
            transition: all 0.3s ease;
            z-index: 998;
        }

        .menu-overlay.active {
            opacity: 1;
            visibility: visible;
        }

        /* 슬라이드 메뉴 */
        .slide-menu {
            position: fixed;
            top: 0;
            left: 0;
            width: 320px;
            max-width: 85vw;
            height: 100%;
            background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
            transform: translateX(-100%);
            transition: transform 0.3s ease;
            z-index: 999;
            overflow-y: auto;
            box-shadow: 4px 0 20px rgba(0, 0, 0, 0.3);
        }

        .slide-menu.active {
            transform: translateX(0);
        }

        .light-mode .slide-menu {
            background: linear-gradient(180deg, #ffffff 0%, #f8f9fa 100%);
            box-shadow: 4px 0 20px rgba(0, 0, 0, 0.1);
        }

        .menu-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }

        .light-mode .menu-header {
            border-bottom: 1px solid rgba(0, 0, 0, 0.1);
        }

        .menu-title {
            font-size: 18px;
            font-weight: 700;
            color: #fff;
        }

        .light-mode .menu-title {
            color: #1a1a2e;
        }

        .menu-close {
            background: none;
            border: none;
            font-size: 24px;
            cursor: pointer;
            color: rgba(255, 255, 255, 0.7);
            padding: 8px;
            border-radius: 8px;
            transition: all 0.3s ease;
        }

        .menu-close:hover {
            background: rgba(255, 255, 255, 0.1);
            color: #fff;
        }

        .light-mode .menu-close {
            color: rgba(0, 0, 0, 0.5);
        }

        .light-mode .menu-close:hover {
            background: rgba(0, 0, 0, 0.1);
            color: #1a1a2e;
        }

        .menu-content {
            padding: 16px 0;
        }

        .menu-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 14px 20px;
            color: rgba(255, 255, 255, 0.9);
            text-decoration: none;
            cursor: pointer;
            transition: all 0.3s ease;
            font-size: 15px;
        }

        .menu-item:hover {
            background: rgba(255, 255, 255, 0.1);
            color: #fff;
        }

        .light-mode .menu-item {
            color: rgba(0, 0, 0, 0.8);
        }

        .light-mode .menu-item:hover {
            background: rgba(0, 0, 0, 0.05);
            color: #1a1a2e;
        }

        .menu-item-icon {
            font-size: 18px;
        }

        /* 서브메뉴 아코디언 */
        .menu-accordion {
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }

        .light-mode .menu-accordion {
            border-bottom: 1px solid rgba(0, 0, 0, 0.05);
        }

        .accordion-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 14px 20px;
            color: rgba(255, 255, 255, 0.9);
            cursor: pointer;
            transition: all 0.3s ease;
            font-size: 15px;
        }

        .accordion-header:hover {
            background: rgba(255, 255, 255, 0.1);
        }

        .light-mode .accordion-header {
            color: rgba(0, 0, 0, 0.8);
        }

        .light-mode .accordion-header:hover {
            background: rgba(0, 0, 0, 0.05);
        }

        .accordion-title {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .accordion-arrow {
            transition: transform 0.3s ease;
            font-size: 12px;
            color: rgba(255, 255, 255, 0.5);
        }

        .accordion-header.active .accordion-arrow {
            transform: rotate(180deg);
        }

        .light-mode .accordion-arrow {
            color: rgba(0, 0, 0, 0.4);
        }

        .slide-menu .accordion-content {
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease;
            background: rgba(0, 0, 0, 0.2);
            padding: 0 !important;
        }

        .slide-menu .accordion-content.active {
            max-height: 500px;
            padding: 8px 0 !important;
        }

        .light-mode .slide-menu .accordion-content {
            background: rgba(0, 0, 0, 0.03);
        }

        .slide-menu .accordion-header {
            cursor: pointer;
        }

        .slide-menu .accordion-header.active .accordion-arrow {
            transform: rotate(180deg);
        }

        .submenu-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 12px 20px 12px 52px;
            color: rgba(255, 255, 255, 0.7);
            cursor: pointer;
            transition: all 0.3s ease;
            font-size: 14px;
        }

        .submenu-item:hover {
            background: rgba(255, 255, 255, 0.08);
            color: #fff;
        }

        .light-mode .submenu-item {
            color: rgba(0, 0, 0, 0.6);
        }

        .light-mode .submenu-item:hover {
            background: rgba(0, 0, 0, 0.05);
            color: #1a1a2e;
        }

        .submenu-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.4);
        }

        .light-mode .submenu-dot {
            background: rgba(0, 0, 0, 0.3);
        }

        /* 가이드 모달 */
        .guide-modal {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.8);
            display: flex;
            justify-content: center;
            align-items: center;
            opacity: 0;
            visibility: hidden;
            transition: all 0.3s ease;
            z-index: 1000;
            padding: 20px;
        }

        .guide-modal.active {
            opacity: 1;
            visibility: visible;
        }

        .guide-modal-content {
            background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
            border-radius: 16px;
            width: 100%;
            max-width: 600px;
            max-height: 80vh;
            overflow-y: auto;
            transform: scale(0.9);
            transition: transform 0.3s ease;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.4);
        }

        .guide-modal.active .guide-modal-content {
            transform: scale(1);
        }

        .light-mode .guide-modal-content {
            background: linear-gradient(180deg, #ffffff 0%, #f8f9fa 100%);
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
        }

        .guide-modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 24px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }

        .light-mode .guide-modal-header {
            border-bottom: 1px solid rgba(0, 0, 0, 0.1);
        }

        .guide-modal-title {
            font-size: 20px;
            font-weight: 700;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .light-mode .guide-modal-title {
            color: #1a1a2e;
        }

        .guide-modal-close {
            background: none;
            border: none;
            font-size: 28px;
            cursor: pointer;
            color: rgba(255, 255, 255, 0.6);
            padding: 4px 8px;
            border-radius: 8px;
            transition: all 0.3s ease;
        }

        .guide-modal-close:hover {
            background: rgba(255, 255, 255, 0.1);
            color: #fff;
        }

        .light-mode .guide-modal-close {
            color: rgba(0, 0, 0, 0.4);
        }

        .light-mode .guide-modal-close:hover {
            background: rgba(0, 0, 0, 0.1);
            color: #1a1a2e;
        }

        .guide-modal-body {
            padding: 24px;
            color: rgba(255, 255, 255, 0.9);
            line-height: 1.8;
        }

        .light-mode .guide-modal-body {
            color: rgba(0, 0, 0, 0.8);
        }

        .guide-modal-body h3 {
            color: #4facfe;
            margin: 20px 0 12px 0;
            font-size: 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .light-mode .guide-modal-body h3 {
            color: #0062cc;
        }

        .guide-modal-body h3:first-child {
            margin-top: 0;
        }

        .guide-modal-body p {
            margin: 0 0 16px 0;
            font-size: 14px;
            color: rgba(255, 255, 255, 0.75);
        }

        .light-mode .guide-modal-body p {
            color: rgba(0, 0, 0, 0.7);
        }

        .guide-modal-body ul {
            margin: 0 0 16px 0;
            padding-left: 20px;
        }

        .guide-modal-body li {
            margin: 8px 0;
            font-size: 14px;
            color: rgba(255, 255, 255, 0.75);
        }

        .light-mode .guide-modal-body li {
            color: rgba(0, 0, 0, 0.7);
        }

        .guide-tip {
            background: rgba(79, 172, 254, 0.15);
            border-left: 4px solid #4facfe;
            padding: 12px 16px;
            border-radius: 0 8px 8px 0;
            margin: 16px 0;
        }

        .light-mode .guide-tip {
            background: rgba(0, 98, 204, 0.1);
            border-left-color: #0062cc;
        }

        .guide-tip-title {
            font-weight: 700;
            color: #4facfe;
            margin-bottom: 6px;
            font-size: 13px;
        }

        .light-mode .guide-tip-title {
            color: #0062cc;
        }

        .guide-tip p {
            margin: 0 !important;
            font-size: 13px !important;
        }

        /* 커뮤니티 모달 */
        .community-modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.8);
            z-index: 2000;
            overflow-y: auto;
            padding: 20px;
            box-sizing: border-box;
        }

        .community-modal.active {
            display: flex;
            justify-content: center;
            align-items: flex-start;
        }

        .community-modal-content {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            border-radius: 16px;
            width: 100%;
            max-width: 700px;
            max-height: 90vh;
            overflow-y: auto;
            border: 1px solid rgba(255, 255, 255, 0.1);
            margin-top: 20px;
        }

        .light-mode .community-modal-content {
            background: linear-gradient(135deg, #ffffff 0%, #f8f9fa 100%);
            border: 1px solid rgba(0, 0, 0, 0.1);
        }

        .community-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 24px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            position: sticky;
            top: 0;
            background: inherit;
            z-index: 10;
        }

        .community-title {
            font-size: 20px;
            font-weight: 700;
            color: #fff;
        }

        .light-mode .community-title {
            color: #1a1a2e;
        }

        .community-close {
            background: none;
            border: none;
            font-size: 28px;
            color: rgba(255, 255, 255, 0.5);
            cursor: pointer;
            padding: 0;
            width: 36px;
            height: 36px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
            transition: all 0.2s;
        }

        .community-close:hover {
            background: rgba(255, 255, 255, 0.1);
            color: #fff;
        }

        .light-mode .community-close {
            color: rgba(0, 0, 0, 0.4);
        }

        .light-mode .community-close:hover {
            background: rgba(0, 0, 0, 0.1);
            color: #1a1a2e;
        }

        /* 커뮤니티 탭 */
        .community-tabs {
            display: flex;
            gap: 8px;
            padding: 16px 24px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            overflow-x: auto;
        }

        .community-tab {
            padding: 8px 16px;
            border: none;
            background: rgba(255, 255, 255, 0.1);
            color: rgba(255, 255, 255, 0.7);
            border-radius: 20px;
            cursor: pointer;
            font-size: 13px;
            white-space: nowrap;
            transition: all 0.2s;
        }

        .community-tab:hover {
            background: rgba(255, 255, 255, 0.15);
        }

        .community-tab.active {
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            color: #fff;
        }

        .light-mode .community-tab {
            background: rgba(0, 0, 0, 0.05);
            color: rgba(0, 0, 0, 0.6);
        }

        .light-mode .community-tab.active {
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            color: #fff;
        }

        /* 글쓰기 폼 */
        .community-write-form {
            margin: 16px 24px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 12px;
            overflow: hidden;
        }

        .light-mode .community-write-form {
            background: rgba(0, 0, 0, 0.03);
        }

        .write-form-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 14px 16px;
            cursor: pointer;
            color: rgba(255, 255, 255, 0.8);
            font-size: 14px;
        }

        .light-mode .write-form-header {
            color: rgba(0, 0, 0, 0.7);
        }

        .write-form-arrow {
            transition: transform 0.3s;
        }

        .write-form-body {
            padding: 16px;
            border-top: 1px solid rgba(255, 255, 255, 0.1);
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .light-mode .write-form-body {
            border-top: 1px solid rgba(0, 0, 0, 0.1);
        }

        .write-form-body input,
        .write-form-body select,
        .write-form-body textarea {
            width: 100%;
            padding: 12px;
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 8px;
            background: rgba(0, 0, 0, 0.2);
            color: #fff;
            font-size: 14px;
            box-sizing: border-box;
        }

        .light-mode .write-form-body input,
        .light-mode .write-form-body select,
        .light-mode .write-form-body textarea {
            border: 1px solid rgba(0, 0, 0, 0.15);
            background: #fff;
            color: #1a1a2e;
        }

        .write-form-body input::placeholder,
        .write-form-body textarea::placeholder {
            color: rgba(255, 255, 255, 0.4);
        }

        .light-mode .write-form-body input::placeholder,
        .light-mode .write-form-body textarea::placeholder {
            color: rgba(0, 0, 0, 0.4);
        }

        .write-form-body textarea {
            resize: vertical;
            min-height: 100px;
        }

        .post-submit-btn {
            padding: 12px 24px;
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            border: none;
            border-radius: 8px;
            color: #fff;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }

        .post-submit-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 15px rgba(79, 172, 254, 0.4);
        }

        /* 게시글 목록 */
        .community-posts {
            padding: 16px 24px;
        }

        .loading-posts {
            text-align: center;
            color: rgba(255, 255, 255, 0.5);
            padding: 40px;
        }

        .light-mode .loading-posts {
            color: rgba(0, 0, 0, 0.5);
        }

        .post-item {
            background: rgba(255, 255, 255, 0.05);
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 12px;
            cursor: pointer;
            transition: all 0.2s;
        }

        .post-item:hover {
            background: rgba(255, 255, 255, 0.1);
            transform: translateY(-2px);
        }

        .light-mode .post-item {
            background: rgba(0, 0, 0, 0.03);
        }

        .light-mode .post-item:hover {
            background: rgba(0, 0, 0, 0.06);
        }

        .post-category {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            margin-bottom: 8px;
        }

        .post-category.question {
            background: rgba(255, 152, 0, 0.2);
            color: #ffb74d;
        }

        .post-category.info {
            background: rgba(76, 175, 80, 0.2);
            color: #81c784;
        }

        .post-category.diary {
            background: rgba(156, 39, 176, 0.2);
            color: #ba68c8;
        }

        .post-title {
            font-size: 15px;
            font-weight: 600;
            color: #fff;
            margin-bottom: 8px;
        }

        .light-mode .post-title {
            color: #1a1a2e;
        }

        .post-meta {
            display: flex;
            gap: 16px;
            font-size: 12px;
            color: rgba(255, 255, 255, 0.5);
        }

        .light-mode .post-meta {
            color: rgba(0, 0, 0, 0.5);
        }

        .post-stats {
            display: flex;
            gap: 12px;
            margin-left: auto;
        }

        .no-posts {
            text-align: center;
            padding: 40px;
            color: rgba(255, 255, 255, 0.5);
        }

        .light-mode .no-posts {
            color: rgba(0, 0, 0, 0.5);
        }

        /* 페이지네이션 */
        .community-pagination {
            display: flex;
            justify-content: center;
            gap: 8px;
            padding: 16px 24px 24px;
        }

        .page-btn {
            padding: 8px 12px;
            border: none;
            background: rgba(255, 255, 255, 0.1);
            color: rgba(255, 255, 255, 0.7);
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            transition: all 0.2s;
        }

        .page-btn:hover {
            background: rgba(255, 255, 255, 0.15);
        }

        .page-btn.active {
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            color: #fff;
        }

        .light-mode .page-btn {
            background: rgba(0, 0, 0, 0.05);
            color: rgba(0, 0, 0, 0.6);
        }

        .light-mode .page-btn.active {
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            color: #fff;
        }

        /* 커뮤니티 플로팅 버튼 */
        .community-float-btn {
            position: fixed;
            bottom: 30px;
            right: 30px;
            width: 60px;
            height: 60px;
            border-radius: 50%;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border: none;
            cursor: pointer;
            box-shadow: 0 4px 20px rgba(102, 126, 234, 0.5);
            z-index: 1000;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.3s;
        }

        .community-float-btn:hover {
            transform: scale(1.1) rotate(10deg);
            box-shadow: 0 6px 30px rgba(102, 126, 234, 0.6);
        }

        .float-icon {
            font-size: 28px;
        }

        .float-badge {
            position: absolute;
            top: -5px;
            right: -5px;
            background: #ff4757;
            color: #fff;
            font-size: 11px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 10px;
            min-width: 18px;
            text-align: center;
        }

        @media (max-width: 768px) {
            .community-float-btn {
                bottom: 20px;
                right: 20px;
                width: 54px;
                height: 54px;
            }

            .float-icon {
                font-size: 24px;
            }

            .community-modal-content {
                margin-top: 10px;
                max-height: 95vh;
            }

            .community-tabs {
                padding: 12px 16px;
            }

            .community-write-form {
                margin: 12px 16px;
            }

            .community-posts {
                padding: 12px 16px;
            }
        }

        /* 헤더 레이아웃 조정 */
        header {
            display: flex;
            align-items: center;
            gap: 16px;
            flex-wrap: wrap;
        }

        .header-left {
            display: flex;
            align-items: center;
            gap: 12px;
            flex: 1;
            min-width: 0;
        }

        .logo {
            min-width: 0;
            flex-shrink: 1;
        }

        .logo h1 {
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .logo .subtitle {
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        /* 모바일 헤더 스타일 */
        @media (max-width: 768px) {
            header {
                flex-direction: column;
                align-items: flex-start;
                gap: 12px;
            }

            .header-left {
                width: 100%;
            }

            .logo h1 {
                font-size: 20px !important;
            }

            .logo .subtitle {
                font-size: 11px !important;
            }

            .header-badges {
                width: 100%;
                display: flex;
                flex-wrap: wrap;
                gap: 6px;
                justify-content: flex-start;
            }

            .header-badge {
                font-size: 10px !important;
                padding: 4px 8px !important;
            }

            .hamburger-btn {
                padding: 8px;
                font-size: 18px;
            }

            .container {
                padding: 12px;
            }

            .search-box {
                padding: 16px !important;
                border-radius: 12px !important;
            }

            .search-form {
                flex-direction: column;
                gap: 10px;
            }

            .input-wrapper {
                width: 100%;
            }

            .search-btn {
                width: 100%;
                justify-content: center;
            }

            .keyword-suggest-box {
                margin-top: 12px;
            }

            .keyword-input-wrapper {
                flex-direction: column;
                gap: 8px;
            }

            .keyword-input {
                width: 100% !important;
            }

            .keyword-suggest-btn {
                width: 100%;
            }

            .trends-section {
                padding: 12px !important;
                border-radius: 12px !important;
            }

            .trends-header {
                flex-wrap: wrap;
                gap: 8px;
            }

            .trends-title {
                font-size: 14px;
            }

            .trends-list {
                display: flex;
                flex-wrap: nowrap;
                overflow-x: auto;
                gap: 8px;
                padding-bottom: 8px;
                -webkit-overflow-scrolling: touch;
                scrollbar-width: thin;
            }

            .trends-list::-webkit-scrollbar {
                height: 4px;
            }

            .trends-list::-webkit-scrollbar-track {
                background: rgba(255,255,255,0.1);
                border-radius: 2px;
            }

            .trends-list::-webkit-scrollbar-thumb {
                background: rgba(102,126,234,0.5);
                border-radius: 2px;
            }

            .trend-item {
                font-size: 12px;
                padding: 6px 10px;
                flex-shrink: 0;
                white-space: nowrap;
            }

            /* 최근 분석 기록 가로 스크롤 */
            .history-list {
                display: flex;
                flex-wrap: nowrap;
                overflow-x: auto;
                gap: 8px;
                padding-bottom: 8px;
                -webkit-overflow-scrolling: touch;
                scrollbar-width: thin;
            }

            .history-list::-webkit-scrollbar {
                height: 4px;
            }

            .history-list::-webkit-scrollbar-track {
                background: rgba(255,255,255,0.1);
                border-radius: 2px;
            }

            .history-list::-webkit-scrollbar-thumb {
                background: rgba(102,126,234,0.5);
                border-radius: 2px;
            }

            .history-item {
                flex-shrink: 0;
                padding: 6px 10px;
            }

            .history-item-name {
                font-size: 12px;
                max-width: 80px;
            }

            .history-item-grade {
                font-size: 10px;
            }

            .history-item-date {
                display: none;
            }

            .history-section {
                padding: 12px !important;
                border-radius: 12px !important;
            }

            .history-header {
                font-size: 13px;
            }
        }

        /* 반응형 슬라이드 메뉴 */
        @media (max-width: 768px) {
            .slide-menu {
                width: 280px;
            }

            .menu-item, .accordion-header {
                font-size: 14px;
                padding: 12px 16px;
            }

            .submenu-item {
                padding: 10px 16px 10px 44px;
                font-size: 13px;
            }

            .guide-modal-content {
                max-height: 90vh;
            }

            .guide-modal-body {
                padding: 20px;
            }
        }
    </style>

    <!-- 카카오 애드핏 스크립트 (한 번만 로드) -->
    <script type="text/javascript" src="//t1.daumcdn.net/kas/static/ba.min.js" async></script>
</head>
<body>
    <!-- 슬라이드 메뉴 오버레이 -->
    <div class="menu-overlay" onclick="closeSlideMenu()"></div>

    <!-- 슬라이드 메뉴 -->
    <nav class="slide-menu" id="slideMenu">
        <div class="menu-header">
            <span class="menu-title">메뉴</span>
            <button class="menu-close" onclick="closeSlideMenu()">&times;</button>
        </div>
        <div class="menu-content">
            <!-- 홈 -->
            <div class="menu-item" onclick="goHome()">
                <span class="menu-item-icon">🏠</span>
                <span>홈</span>
            </div>

            <!-- 키워드 분석 가이드 아코디언 -->
            <div class="menu-accordion">
                <div class="accordion-header" onclick="toggleAccordion(this)">
                    <div class="accordion-title">
                        <span class="menu-item-icon">📚</span>
                        <span>키워드 분석 가이드</span>
                    </div>
                    <span class="accordion-arrow">▼</span>
                </div>
                <div class="accordion-content">
                    <div class="submenu-item" onclick="showGuide('keyword-selection')">
                        <span class="submenu-dot"></span>
                        <span>키워드 선정법</span>
                    </div>
                    <div class="submenu-item" onclick="showGuide('search-volume')">
                        <span class="submenu-dot"></span>
                        <span>검색량 확인하기</span>
                    </div>
                    <div class="submenu-item" onclick="showGuide('longtail')">
                        <span class="submenu-dot"></span>
                        <span>롱테일 키워드란?</span>
                    </div>
                    <div class="submenu-item" onclick="showGuide('keyword-placement')">
                        <span class="submenu-dot"></span>
                        <span>키워드 배치 전략</span>
                    </div>
                    <div class="submenu-item" onclick="showGuide('trend-keyword')">
                        <span class="submenu-dot"></span>
                        <span>시즌/트렌드 키워드</span>
                    </div>
                </div>
            </div>

            <!-- 블로그 성장 팁 아코디언 -->
            <div class="menu-accordion">
                <div class="accordion-header" onclick="toggleAccordion(this)">
                    <div class="accordion-title">
                        <span class="menu-item-icon">📈</span>
                        <span>블로그 성장 팁</span>
                    </div>
                    <span class="accordion-arrow">▼</span>
                </div>
                <div class="accordion-content">
                    <div class="submenu-item" onclick="showGuide('c-rank')">
                        <span class="submenu-dot"></span>
                        <span>C-Rank 알고리즘</span>
                    </div>
                    <div class="submenu-item" onclick="showGuide('optimization')">
                        <span class="submenu-dot"></span>
                        <span>최적화 블로그 만들기</span>
                    </div>
                    <div class="submenu-item" onclick="showGuide('seo')">
                        <span class="submenu-dot"></span>
                        <span>SEO 최적화 방법</span>
                    </div>
                    <div class="submenu-item" onclick="showGuide('title')">
                        <span class="submenu-dot"></span>
                        <span>제목 작성법</span>
                    </div>
                    <div class="submenu-item" onclick="showGuide('image')">
                        <span class="submenu-dot"></span>
                        <span>이미지 최적화</span>
                    </div>
                    <div class="submenu-item" onclick="showGuide('posting-strategy')">
                        <span class="submenu-dot"></span>
                        <span>꾸준한 포스팅 전략</span>
                    </div>
                    <div class="submenu-item" onclick="showGuide('avoid-lowquality')">
                        <span class="submenu-dot"></span>
                        <span>저품질 피하는 방법</span>
                    </div>
                </div>
            </div>

            <!-- 커뮤니티 -->
            <a href="/community" class="menu-item" style="text-decoration: none; color: inherit;">
                <span class="menu-item-icon">💬</span>
                <span>커뮤니티</span>
                <span style="margin-left: auto; background: #4CAF50; color: white; padding: 2px 6px; border-radius: 10px; font-size: 10px;">NEW</span>
            </a>

            <!-- 사용법 -->
            <div class="menu-item" onclick="showGuide('usage')">
                <span class="menu-item-icon">❓</span>
                <span>사용법</span>
            </div>
        </div>
    </nav>

    <!-- 가이드 모달 -->
    <div class="guide-modal" id="guideModal" onclick="closeGuideModal(event)">
        <div class="guide-modal-content" onclick="event.stopPropagation()">
            <div class="guide-modal-header">
                <div class="guide-modal-title" id="guideModalTitle">가이드</div>
                <button class="guide-modal-close" onclick="closeGuideModal()">&times;</button>
            </div>
            <div class="guide-modal-body" id="guideModalBody">
                <!-- 가이드 내용이 여기에 표시됩니다 -->
            </div>
        </div>
    </div>

    <!-- 커뮤니티 모달 -->
    <div class="community-modal" id="communityModal" onclick="closeCommunity(event)">
        <div class="community-modal-content" onclick="event.stopPropagation()">
            <div class="community-header">
                <div class="community-title">💬 블로거 커뮤니티</div>
                <button class="community-close" onclick="closeCommunity()">&times;</button>
            </div>

            <!-- 카테고리 탭 -->
            <div class="community-tabs">
                <button class="community-tab active" onclick="switchCommunityTab('all')">전체</button>
                <button class="community-tab" onclick="switchCommunityTab('question')">질문</button>
                <button class="community-tab" onclick="switchCommunityTab('info')">정보공유</button>
                <button class="community-tab" onclick="switchCommunityTab('diary')">성장일기</button>
            </div>

            <!-- 글쓰기 폼 -->
            <div class="community-write-form" id="communityWriteForm">
                <div class="write-form-header" onclick="toggleWriteForm()">
                    <span>✏️ 새 글 작성하기</span>
                    <span class="write-form-arrow">▼</span>
                </div>
                <div class="write-form-body" style="display: none;">
                    <input type="text" id="postNickname" placeholder="닉네임 (익명 가능)" maxlength="20">
                    <select id="postCategory">
                        <option value="question">질문</option>
                        <option value="info">정보공유</option>
                        <option value="diary">성장일기</option>
                    </select>
                    <input type="text" id="postTitle" placeholder="제목을 입력하세요" maxlength="100">
                    <textarea id="postContent" placeholder="내용을 입력하세요 (마크다운 지원)" rows="5"></textarea>
                    <button class="post-submit-btn" onclick="submitPost()">작성하기</button>
                </div>
            </div>

            <!-- 게시글 목록 -->
            <div class="community-posts" id="communityPosts">
                <div class="loading-posts">게시글을 불러오는 중...</div>
            </div>

            <!-- 페이지네이션 -->
            <div class="community-pagination" id="communityPagination"></div>
        </div>
    </div>

    <!-- 커뮤니티 플로팅 버튼 -->
    <a href="/community" class="community-float-btn" title="커뮤니티">
        <span class="float-icon">💬</span>
    </a>

    <!-- 사이드바 광고 (160x600) - PC에서만 표시 -->
    <div class="ad-sidebar ad-sidebar-right">
        <div class="ad-sidebar-container">
            <div class="ad-sidebar-label">광고</div>
            <ins class="kakao_ad_area" style="display:none;"
            data-ad-unit = "DAN-qL9yUvEpDkygjMA5"
            data-ad-width = "160"
            data-ad-height = "600"></ins>
        </div>
    </div>

    <!-- 테마 토글 버튼 -->
    <button class="theme-toggle" onclick="toggleTheme()" title="다크/라이트 모드 전환">🌙</button>

    <div class="container">
        <header>
            <div class="header-left">
                <button class="hamburger-btn" onclick="openSlideMenu()" title="메뉴 열기">☰</button>
                <div class="logo">
                    <div>
                        <h1>블로그 지수 분석기</h1>
                        <p class="subtitle">검색 노출 확인 · 키워드 분석</p>
                    </div>
                </div>
            </div>
            <div class="header-badges">
                <span class="header-badge">🔍 실시간 노출 체크</span>
                <span class="header-badge">📈 성장 분석</span>
                <span class="header-badge">🎯 키워드 경쟁도</span>
            </div>
        </header>
        
        <div class="search-box">
            <form class="search-form" onsubmit="analyzeBlog(event)">
                <div class="input-wrapper">
                    <span class="input-prefix">blog.naver.com/</span>
                    <input type="text" id="blogId" placeholder="블로그 아이디 입력" autocomplete="off">
                </div>
                <button type="submit" class="search-btn" id="searchBtn">
                    🔍 분석하기
                </button>
            </form>

            <!-- 키워드 추천 섹션 -->
            <div class="keyword-suggest-box">
                <div class="keyword-input-wrapper">
                    <input type="text" id="keywordInput" class="keyword-input" placeholder="키워드를 입력하면 관련 키워드를 추천해드립니다" autocomplete="off">
                    <button type="button" class="keyword-suggest-btn" onclick="getKeywordSuggestions()">연관 키워드</button>
                </div>
                <div id="suggestResults" class="suggest-results">
                    <div class="suggest-label">연관 키워드 (클릭하여 복사)</div>
                    <div id="suggestTags" class="suggest-tags"></div>
                </div>
            </div>
        </div>

        <!-- 트렌드 키워드 섹션 -->
        <div id="trendsSection" class="trends-section">
            <div class="trends-header">
                <span class="trends-title">🔥 실시간 인기 키워드</span>
                <span id="trendsSource" class="trends-source"></span>
                <button class="trends-refresh-btn" onclick="loadTrendKeywords()">새로고침</button>
            </div>
            <div id="trendsList" class="trends-list">
                <span style="color: #ffffff80; font-size: 12px;">로딩 중...</span>
            </div>
        </div>

        <!-- 메인 페이지 광고 (250x250) -->
        <div class="ad-content-wrapper hide-mobile" id="adMainSection">
            <div class="ad-content-container">
                <div class="ad-label">광고</div>
                <ins class="kakao_ad_area" style="display:none;"
                data-ad-unit = "DAN-swwvk4Kp8cMpG1FI"
                data-ad-width = "250"
                data-ad-height = "250"></ins>
            </div>
        </div>

        <!-- 검색 히스토리 섹션 -->
        <div id="historySection" class="history-section" style="display: none;">
            <div class="history-header">
                <span class="history-title">최근 분석 기록</span>
                <div>
                    <button class="compare-btn" onclick="showHistoryData()">🔍 저장 데이터 확인</button>
                    <button class="compare-btn" onclick="showCompareModal()">📊 이전 기록과 비교</button>
                    <button class="history-clear-btn" onclick="clearHistory()">전체 삭제</button>
                </div>
            </div>
            <div id="historyList" class="history-list"></div>
        </div>

        <div id="result"></div>

        <!-- 푸터 광고 (300x250) -->
        <div class="ad-footer-wrapper">
            <div class="ad-content-container">
                <div class="ad-label">광고</div>
                <ins class="kakao_ad_area" style="display:none;"
                data-ad-unit = "DAN-qYU1Nbac9rUaGFpF"
                data-ad-width = "300"
                data-ad-height = "250"></ins>
            </div>
        </div>

        <!-- 푸터 -->
        <footer class="footer">
            <div class="footer-disclaimer">
                <h4>서비스 이용 안내</h4>
                <ul>
                    <li>본 서비스는 공개된 블로그 정보를 분석하여 참고용 지표를 제공합니다.</li>
                    <li>분석 결과는 자체 알고리즘 기반의 추정치이며, 네이버 공식 지수가 아닙니다.</li>
                    <li>본 서비스는 네이버와 무관한 독립 서비스입니다.</li>
                </ul>
            </div>
            <div class="footer-links">
                <a href="/privacy">개인정보처리방침</a>
                <a href="/terms">이용약관</a>
                <a href="/disclaimer">면책조항</a>
            </div>
            <div class="footer-copyright">
                Blog Index Analyzer &copy; 2025 |
                데이터 출처: <a href="https://blog.naver.com" target="_blank" rel="noopener">네이버 블로그</a>
            </div>
        </footer>
    </div>
    
    <script>
        // =====================================================
        // 슬라이드 메뉴 및 가이드 관리
        // =====================================================

        // 슬라이드 메뉴 열기
        function openSlideMenu() {
            document.getElementById('slideMenu').classList.add('active');
            document.querySelector('.menu-overlay').classList.add('active');
            document.body.style.overflow = 'hidden';
        }

        // 슬라이드 메뉴 닫기
        function closeSlideMenu() {
            document.getElementById('slideMenu').classList.remove('active');
            document.querySelector('.menu-overlay').classList.remove('active');
            document.body.style.overflow = '';
        }

        // 홈으로 이동
        function goHome() {
            closeSlideMenu();
            window.scrollTo({ top: 0, behavior: 'smooth' });
            // 결과 영역 숨기기
            const resultSection = document.getElementById('resultSection');
            if (resultSection) {
                resultSection.style.display = 'none';
            }
        }

        // 아코디언 토글
        function toggleAccordion(header) {
            const content = header.nextElementSibling;
            const isActive = header.classList.contains('active');

            // 모든 아코디언 닫기
            document.querySelectorAll('.accordion-header').forEach(h => {
                h.classList.remove('active');
                h.nextElementSibling.classList.remove('active');
            });

            // 클릭한 아코디언만 열기 (이미 열려있었다면 닫힌 상태 유지)
            if (!isActive) {
                header.classList.add('active');
                content.classList.add('active');
            }
        }

        // 가이드 내용 데이터
        const guideContents = {
            'keyword-selection': {
                title: '📝 키워드 선정법',
                content: `
                    <h3>🎯 키워드 선정의 핵심 원칙</h3>
                    <p>효과적인 키워드 선정은 블로그 성장의 첫 걸음입니다. 검색량과 경쟁도의 균형을 맞추는 것이 중요합니다.</p>

                    <h3>✅ 좋은 키워드의 조건</h3>
                    <ul>
                        <li><strong>적절한 검색량:</strong> 월간 검색량 1,000~10,000 사이가 적당합니다</li>
                        <li><strong>낮은 경쟁도:</strong> 상위 노출 블로그 수가 적을수록 유리합니다</li>
                        <li><strong>명확한 검색 의도:</strong> 사용자가 원하는 정보가 명확한 키워드</li>
                        <li><strong>내 전문 분야:</strong> 자신있게 글을 쓸 수 있는 주제</li>
                    </ul>

                    <h3>📊 키워드 분석 단계</h3>
                    <ul>
                        <li>1. 주제 관련 키워드 브레인스토밍</li>
                        <li>2. 검색량 및 경쟁도 확인</li>
                        <li>3. 상위 노출 글 분석</li>
                        <li>4. 차별화 포인트 찾기</li>
                    </ul>

                    <div class="guide-tip">
                        <div class="guide-tip-title">💡 TIP</div>
                        <p>처음에는 경쟁이 낮은 롱테일 키워드로 시작하여 블로그 지수를 올린 후, 점차 경쟁이 높은 키워드에 도전하세요!</p>
                    </div>
                `
            },
            'search-volume': {
                title: '🔍 검색량 확인하기',
                content: `
                    <h3>📈 검색량 확인 방법</h3>
                    <p>키워드의 검색량을 파악하면 콘텐츠의 잠재적 도달 범위를 예측할 수 있습니다.</p>

                    <h3>🛠 활용 가능한 도구</h3>
                    <ul>
                        <li><strong>네이버 검색광고:</strong> 키워드 도구에서 월간 검색량 확인</li>
                        <li><strong>네이버 데이터랩:</strong> 키워드 트렌드 및 연령/성별 분포</li>
                        <li><strong>블로그 분석기:</strong> 키워드 경쟁도와 함께 확인</li>
                    </ul>

                    <h3>📊 검색량 해석 가이드</h3>
                    <ul>
                        <li><strong>10,000 이상:</strong> 높은 검색량, 경쟁 치열</li>
                        <li><strong>1,000~10,000:</strong> 적정 검색량, 도전 가치 있음</li>
                        <li><strong>100~1,000:</strong> 낮은 검색량, 상위 노출 용이</li>
                        <li><strong>100 미만:</strong> 매우 낮음, 틈새 시장</li>
                    </ul>

                    <div class="guide-tip">
                        <div class="guide-tip-title">💡 TIP</div>
                        <p>검색량만 보지 말고, 계절성과 트렌드도 함께 확인하세요. 특정 시즌에만 검색량이 급증하는 키워드도 있습니다!</p>
                    </div>
                `
            },
            'longtail': {
                title: '🔗 롱테일 키워드란?',
                content: `
                    <h3>📌 롱테일 키워드 정의</h3>
                    <p>롱테일 키워드는 3개 이상의 단어로 구성된 구체적인 검색어입니다. 검색량은 적지만 전환율이 높고 경쟁이 적습니다.</p>

                    <h3>📊 예시 비교</h3>
                    <ul>
                        <li><strong>빅 키워드:</strong> "노트북" (검색량 높음, 경쟁 치열)</li>
                        <li><strong>미들 키워드:</strong> "노트북 추천" (중간 수준)</li>
                        <li><strong>롱테일:</strong> "대학생 가성비 노트북 추천 2024" (경쟁 낮음)</li>
                    </ul>

                    <h3>✅ 롱테일 키워드의 장점</h3>
                    <ul>
                        <li>상위 노출 달성이 상대적으로 쉬움</li>
                        <li>검색 의도가 명확하여 양질의 방문자 유입</li>
                        <li>블로그 초보자에게 적합</li>
                        <li>다양한 롱테일로 트래픽 누적 가능</li>
                    </ul>

                    <div class="guide-tip">
                        <div class="guide-tip-title">💡 TIP</div>
                        <p>네이버 자동완성이나 연관 검색어를 활용하면 롱테일 키워드를 쉽게 찾을 수 있습니다!</p>
                    </div>
                `
            },
            'seo': {
                title: '⚡ SEO 최적화 방법',
                content: `
                    <h3>🎯 SEO란?</h3>
                    <p>SEO(검색 엔진 최적화)는 검색 결과에서 상위에 노출되도록 콘텐츠를 최적화하는 것입니다.</p>

                    <h3>📝 제목 최적화</h3>
                    <ul>
                        <li>핵심 키워드를 제목 앞쪽에 배치</li>
                        <li>30~45자 내외로 작성</li>
                        <li>클릭을 유도하는 매력적인 제목</li>
                    </ul>

                    <h3>📄 본문 최적화</h3>
                    <ul>
                        <li>첫 문단에 핵심 키워드 자연스럽게 포함</li>
                        <li>소제목(H2, H3)에도 키워드 활용</li>
                        <li>1,500자 이상의 충분한 내용</li>
                        <li>단락 구분과 가독성 있는 구성</li>
                    </ul>

                    <h3>🖼 이미지 최적화</h3>
                    <ul>
                        <li>이미지 파일명에 키워드 포함</li>
                        <li>ALT 태그 필수 작성</li>
                        <li>적절한 이미지 수 (3~10장)</li>
                    </ul>

                    <div class="guide-tip">
                        <div class="guide-tip-title">💡 TIP</div>
                        <p>키워드를 억지로 넣기보다 자연스러운 문맥에서 사용하세요. 과도한 키워드 반복은 오히려 역효과입니다!</p>
                    </div>
                `
            },
            'title': {
                title: '✏️ 제목 작성법',
                content: `
                    <h3>📏 적절한 제목 길이</h3>
                    <p>네이버 검색 결과에서 잘리지 않는 30~45자가 이상적입니다.</p>

                    <h3>🎯 키워드 배치</h3>
                    <ul>
                        <li>핵심 키워드는 제목 앞쪽에 배치</li>
                        <li>자연스러운 문장 형태 유지</li>
                        <li>보조 키워드는 뒤쪽에 배치</li>
                    </ul>

                    <h3>✅ 좋은 제목 공식</h3>
                    <ul>
                        <li><strong>숫자 활용:</strong> "2024년 추천 노트북 TOP 5"</li>
                        <li><strong>질문형:</strong> "초보자도 쉽게? 블로그 시작하는 방법"</li>
                        <li><strong>해결형:</strong> "고민 끝! 여행 짐싸기 완벽 가이드"</li>
                        <li><strong>비교형:</strong> "A vs B 무엇이 더 좋을까?"</li>
                    </ul>

                    <h3>❌ 피해야 할 제목</h3>
                    <ul>
                        <li>키워드만 나열한 제목</li>
                        <li>특수문자 과다 사용</li>
                        <li>너무 길거나 짧은 제목</li>
                        <li>내용과 맞지 않는 낚시성 제목</li>
                    </ul>

                    <div class="guide-tip">
                        <div class="guide-tip-title">💡 TIP</div>
                        <p>상위 노출된 글의 제목 패턴을 분석하고, 자신만의 차별점을 더해보세요!</p>
                    </div>
                `
            },
            'image': {
                title: '🖼 이미지 최적화',
                content: `
                    <h3>📁 파일명 최적화</h3>
                    <p>이미지 파일명에 키워드를 포함하면 이미지 검색에서도 노출될 수 있습니다.</p>
                    <ul>
                        <li>❌ IMG_1234.jpg</li>
                        <li>✅ 서울맛집_강남역_파스타.jpg</li>
                    </ul>

                    <h3>🏷 ALT 태그 작성</h3>
                    <p>ALT 태그는 이미지를 설명하는 텍스트로, 검색 엔진이 이미지를 이해하는 데 도움을 줍니다.</p>
                    <ul>
                        <li>이미지 내용을 정확히 설명</li>
                        <li>핵심 키워드 자연스럽게 포함</li>
                        <li>간결하게 작성 (125자 이내)</li>
                    </ul>

                    <h3>📊 적절한 이미지 수</h3>
                    <ul>
                        <li>최소 3장 이상 권장</li>
                        <li>글 길이에 따라 5~10장 적당</li>
                        <li>이미지마다 관련 설명 추가</li>
                    </ul>

                    <h3>⚡ 용량 최적화</h3>
                    <ul>
                        <li>200KB 이하로 압축 권장</li>
                        <li>WebP 포맷 활용 고려</li>
                        <li>적절한 크기로 리사이징</li>
                    </ul>

                    <div class="guide-tip">
                        <div class="guide-tip-title">💡 TIP</div>
                        <p>직접 촬영한 사진이 저작권 문제도 없고, 검색 엔진에서도 더 좋은 평가를 받습니다!</p>
                    </div>
                `
            },
            'usage': {
                title: '❓ 블로그 분석기 사용법',
                content: `
                    <h3>🔍 블로그 분석하기</h3>
                    <ul>
                        <li>1. 상단 입력창에 네이버 블로그 아이디 입력</li>
                        <li>2. "분석하기" 버튼 클릭</li>
                        <li>3. 블로그 지수, 최근 글 분석 결과 확인</li>
                        <li>4. AI 코칭 내용으로 개선점 파악</li>
                    </ul>

                    <h3>🎯 키워드 분석하기</h3>
                    <ul>
                        <li>1. 키워드 입력창에 분석할 키워드 입력</li>
                        <li>2. "연관 키워드" 버튼으로 관련 키워드 확인</li>
                        <li>3. 검색량과 경쟁도 참고하여 키워드 선정</li>
                    </ul>

                    <h3>📈 결과 해석하기</h3>
                    <ul>
                        <li><strong>블로그 지수:</strong> 0~100 사이의 점수로 블로그 영향력 표시</li>
                        <li><strong>검색 노출:</strong> 해당 키워드로 상위 노출 가능성</li>
                        <li><strong>경쟁도:</strong> 낮을수록 상위 노출이 쉬움</li>
                    </ul>

                    <h3>💡 활용 팁</h3>
                    <ul>
                        <li>주기적으로 블로그 지수 변화 확인</li>
                        <li>글 발행 전 키워드 경쟁도 체크</li>
                        <li>AI 코칭 내용을 바탕으로 글 수정</li>
                    </ul>

                    <div class="guide-tip">
                        <div class="guide-tip-title">💡 TIP</div>
                        <p>분석 결과를 참고하되, 가장 중요한 것은 꾸준한 양질의 콘텐츠 발행입니다!</p>
                    </div>
                `
            },
            'keyword-placement': {
                title: '📍 키워드 배치 전략',
                content: `
                    <h3>🎯 키워드 배치의 핵심</h3>
                    <p>키워드는 <strong>자연스럽게</strong> 배치하는 것이 중요합니다. 과도한 반복은 저품질 판정의 원인이 됩니다.</p>

                    <h3>📝 제목에 키워드 배치</h3>
                    <ul>
                        <li><strong>핵심 키워드는 제목 앞쪽에</strong> - 검색 결과에서 먼저 보임</li>
                        <li>제목 길이: <strong>25~45자</strong> 권장</li>
                        <li>자연스러운 문장 형태 유지</li>
                    </ul>

                    <h3>📄 본문 키워드 배치</h3>
                    <ul>
                        <li><strong>첫 문단:</strong> 핵심 키워드 1회 자연스럽게 포함</li>
                        <li><strong>소제목(H2/H3):</strong> 키워드 변형 활용</li>
                        <li><strong>본문 중간:</strong> 300~500자마다 관련 키워드 언급</li>
                        <li><strong>마지막 문단:</strong> 핵심 키워드로 마무리</li>
                    </ul>

                    <h3>🏷 태그 활용</h3>
                    <ul>
                        <li>핵심 키워드를 첫 번째 태그로</li>
                        <li>연관 키워드 5~10개 추가</li>
                        <li>롱테일 키워드도 태그에 포함</li>
                    </ul>

                    <h3>⚠️ 주의사항</h3>
                    <ul>
                        <li>❌ 같은 키워드 5회 이상 반복 금지</li>
                        <li>❌ 키워드만 나열하는 문장 금지</li>
                        <li>❌ 내용과 관련 없는 키워드 삽입 금지</li>
                    </ul>

                    <div class="guide-tip">
                        <div class="guide-tip-title">💡 TIP</div>
                        <p>키워드 밀도는 본문의 1~2% 정도가 적당합니다. 독자가 읽었을 때 어색하지 않은 수준을 유지하세요!</p>
                    </div>
                `
            },
            'trend-keyword': {
                title: '📅 시즌/트렌드 키워드',
                content: `
                    <h3>📈 트렌드 키워드란?</h3>
                    <p>특정 시기나 이슈에 따라 검색량이 급증하는 키워드입니다. 타이밍을 맞추면 폭발적인 유입이 가능합니다.</p>

                    <h3>🗓 시즌 키워드 예시</h3>
                    <ul>
                        <li><strong>1~2월:</strong> 새해 계획, 다이어트, 졸업선물</li>
                        <li><strong>3~4월:</strong> 벚꽃명소, 신학기, 봄옷 코디</li>
                        <li><strong>5~6월:</strong> 어버이날, 스승의날, 여름휴가</li>
                        <li><strong>7~8월:</strong> 피서지, 물놀이, 에어컨</li>
                        <li><strong>9~10월:</strong> 추석, 단풍, 가을여행</li>
                        <li><strong>11~12월:</strong> 크리스마스, 연말정산, 송년회</li>
                    </ul>

                    <h3>⚡ 실시간 트렌드 활용</h3>
                    <ul>
                        <li><strong>네이버 실검:</strong> 실시간 급상승 검색어 확인</li>
                        <li><strong>구글 트렌드:</strong> 키워드 트렌드 분석</li>
                        <li><strong>SNS 해시태그:</strong> 인스타/트위터 인기 해시태그</li>
                    </ul>

                    <h3>🎯 트렌드 키워드 전략</h3>
                    <ul>
                        <li><strong>2~3주 전 선점:</strong> 시즌 키워드는 미리 포스팅</li>
                        <li><strong>빠른 대응:</strong> 이슈 키워드는 24시간 내 발행</li>
                        <li><strong>차별화:</strong> 같은 주제라도 독특한 관점 제시</li>
                    </ul>

                    <div class="guide-tip">
                        <div class="guide-tip-title">💡 TIP</div>
                        <p>시즌 키워드는 미리 캘린더에 기록해두고, 2~3주 전부터 준비하세요. 선점 효과가 매우 큽니다!</p>
                    </div>
                `
            },
            'c-rank': {
                title: '🏆 C-Rank 알고리즘 이해하기',
                content: `
                    <h3>🔍 C-Rank란?</h3>
                    <p>네이버의 <strong>Creator Rank</strong> 알고리즘으로, 블로그의 신뢰도와 전문성을 평가하여 검색 순위에 반영합니다.</p>

                    <h3>📊 C-Rank 평가 요소</h3>
                    <ul>
                        <li><strong>주제 전문성 (40%):</strong> 특정 분야에 대한 깊이 있는 콘텐츠</li>
                        <li><strong>활동 지속성 (30%):</strong> 꾸준한 포스팅 빈도</li>
                        <li><strong>사용자 반응 (20%):</strong> 공감, 댓글, 체류 시간</li>
                        <li><strong>콘텐츠 품질 (10%):</strong> 글자수, 이미지, 구성</li>
                    </ul>

                    <h3>🎯 C-Rank 높이는 방법</h3>
                    <ul>
                        <li><strong>주제 집중:</strong> 1~2개 주제에 집중하여 전문성 확보</li>
                        <li><strong>꾸준한 포스팅:</strong> 주 3~5회 정기적 발행</li>
                        <li><strong>양질의 콘텐츠:</strong> 2,500자 이상, 이미지 6~13개</li>
                        <li><strong>독자 소통:</strong> 댓글 답변, 공감 유도</li>
                    </ul>

                    <h3>⚠️ C-Rank에 불리한 행동</h3>
                    <ul>
                        <li>❌ 여러 주제를 무분별하게 다루기</li>
                        <li>❌ 불규칙한 포스팅 (한 달에 1~2개)</li>
                        <li>❌ 짧은 글, 이미지 없는 글</li>
                        <li>❌ 복사/붙여넣기 콘텐츠</li>
                    </ul>

                    <div class="guide-tip">
                        <div class="guide-tip-title">💡 TIP</div>
                        <p>C-Rank는 단기간에 올리기 어렵습니다. 최소 3개월 이상 꾸준히 양질의 콘텐츠를 발행해야 효과를 볼 수 있습니다!</p>
                    </div>
                `
            },
            'optimization': {
                title: '⚡ 최적화 블로그 만들기',
                content: `
                    <h3>📏 업계 표준 기준 (2024~2025)</h3>
                    <p>블로그 최적화를 위한 <strong>업계 권장 기준</strong>을 정리했습니다.</p>

                    <h3>📝 글자수 기준</h3>
                    <ul>
                        <li><strong>최소:</strong> 1,500자 이상</li>
                        <li><strong>권장:</strong> 2,500~3,000자</li>
                        <li><strong>최적:</strong> 2,800자 (공백 미포함)</li>
                    </ul>

                    <h3>🖼 이미지 기준</h3>
                    <ul>
                        <li><strong>정보성 포스팅:</strong> 6~13개</li>
                        <li><strong>리뷰 포스팅:</strong> 10~20개</li>
                        <li><strong>300~500자마다:</strong> 이미지 1장 배치</li>
                    </ul>

                    <h3>📑 소제목(H2/H3) 기준</h3>
                    <ul>
                        <li><strong>권장:</strong> 4~5개 이상</li>
                        <li><strong>구성:</strong> 주제를 4~5가지로 분류</li>
                        <li><strong>효과:</strong> 가독성 향상 + 스니펫 노출</li>
                    </ul>

                    <h3>📊 최적화 점수 체크리스트</h3>
                    <table style="width:100%; border-collapse: collapse; margin: 10px 0;">
                        <tr style="background: #4caf5033;">
                            <td style="padding: 8px; border: 1px solid #ffffff33;">항목</td>
                            <td style="padding: 8px; border: 1px solid #ffffff33;">기준</td>
                            <td style="padding: 8px; border: 1px solid #ffffff33;">배점</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px; border: 1px solid #ffffff33;">제목</td>
                            <td style="padding: 8px; border: 1px solid #ffffff33;">25~45자</td>
                            <td style="padding: 8px; border: 1px solid #ffffff33;">15점</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px; border: 1px solid #ffffff33;">이미지</td>
                            <td style="padding: 8px; border: 1px solid #ffffff33;">6~13개</td>
                            <td style="padding: 8px; border: 1px solid #ffffff33;">20점</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px; border: 1px solid #ffffff33;">본문</td>
                            <td style="padding: 8px; border: 1px solid #ffffff33;">2,500자+</td>
                            <td style="padding: 8px; border: 1px solid #ffffff33;">25점</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px; border: 1px solid #ffffff33;">소제목</td>
                            <td style="padding: 8px; border: 1px solid #ffffff33;">4개+</td>
                            <td style="padding: 8px; border: 1px solid #ffffff33;">15점</td>
                        </tr>
                    </table>

                    <div class="guide-tip">
                        <div class="guide-tip-title">💡 TIP</div>
                        <p>기준을 맞추는 것도 중요하지만, 독자에게 실질적인 가치를 제공하는 것이 최우선입니다!</p>
                    </div>
                `
            },
            'posting-strategy': {
                title: '📅 꾸준한 포스팅 전략',
                content: `
                    <h3>⏰ 최적의 포스팅 빈도</h3>
                    <ul>
                        <li><strong>초보자:</strong> 주 3회 이상</li>
                        <li><strong>중급자:</strong> 주 5회 이상</li>
                        <li><strong>최적화 목표:</strong> 매일 1포스팅</li>
                    </ul>

                    <h3>🕐 최적의 발행 시간</h3>
                    <ul>
                        <li><strong>평일:</strong> 오전 7~9시, 점심 12~1시, 저녁 6~8시</li>
                        <li><strong>주말:</strong> 오전 10~12시</li>
                        <li><strong>타겟 독자의 활동 시간 고려</strong></li>
                    </ul>

                    <h3>📋 콘텐츠 플래닝</h3>
                    <ul>
                        <li><strong>월간 계획:</strong> 한 달 치 주제 미리 선정</li>
                        <li><strong>주간 계획:</strong> 요일별 카테고리 지정</li>
                        <li><strong>시즌 준비:</strong> 2~3주 전 시즌 콘텐츠 발행</li>
                    </ul>

                    <h3>🔄 지속 가능한 루틴 만들기</h3>
                    <ul>
                        <li>글감 아이디어 수시로 메모</li>
                        <li>이미지/자료는 미리 수집</li>
                        <li>예약 발행 기능 적극 활용</li>
                        <li>번아웃 방지를 위한 버퍼 글 확보</li>
                    </ul>

                    <div class="guide-tip">
                        <div class="guide-tip-title">💡 TIP</div>
                        <p>양보다 질! 무리하게 매일 발행하다 지치는 것보다, 꾸준히 양질의 글을 발행하는 것이 중요합니다.</p>
                    </div>
                `
            },
            'avoid-lowquality': {
                title: '🚫 저품질 피하는 방법',
                content: `
                    <h3>⚠️ 저품질 블로그란?</h3>
                    <p>네이버가 <strong>품질이 낮다고 판단한 블로그</strong>로, 검색 결과에서 노출이 급격히 감소합니다.</p>

                    <h3>❌ 저품질 판정 원인</h3>
                    <ul>
                        <li><strong>복사/붙여넣기:</strong> 다른 글 그대로 복사</li>
                        <li><strong>키워드 남용:</strong> 같은 키워드 과도한 반복</li>
                        <li><strong>어뷰징:</strong> 클릭 유도, 허위 정보</li>
                        <li><strong>무의미한 글:</strong> 짧고 내용 없는 포스팅</li>
                        <li><strong>과도한 광고:</strong> 광고성 글만 발행</li>
                        <li><strong>매크로 사용:</strong> 자동화 도구 사용</li>
                    </ul>

                    <h3>✅ 저품질 예방 수칙</h3>
                    <ul>
                        <li><strong>100% 직접 작성:</strong> 복사 금지, 직접 쓰기</li>
                        <li><strong>키워드 자연스럽게:</strong> 본문의 1~2% 이내</li>
                        <li><strong>충분한 내용:</strong> 1,500자 이상 작성</li>
                        <li><strong>직접 촬영 이미지:</strong> 저작권 문제 없는 이미지</li>
                        <li><strong>정확한 정보:</strong> 팩트 체크 필수</li>
                    </ul>

                    <h3>🔄 저품질 탈출 방법</h3>
                    <ul>
                        <li>문제 있는 글 삭제 또는 수정</li>
                        <li>2~3주간 양질의 글 꾸준히 발행</li>
                        <li>독자와 적극적으로 소통</li>
                        <li>주제 일관성 유지</li>
                    </ul>

                    <div class="guide-tip">
                        <div class="guide-tip-title">💡 TIP</div>
                        <p>저품질에 걸리면 회복에 최소 2~4주가 소요됩니다. 예방이 최선입니다!</p>
                    </div>
                `
            }
        };

        // 가이드 모달 표시
        function showGuide(guideId) {
            const guide = guideContents[guideId];
            if (!guide) return;

            document.getElementById('guideModalTitle').innerHTML = guide.title;
            document.getElementById('guideModalBody').innerHTML = guide.content;
            document.getElementById('guideModal').classList.add('active');
            document.body.style.overflow = 'hidden';

            closeSlideMenu();
        }

        // 가이드 모달 닫기
        function closeGuideModal(event) {
            if (event && event.target !== event.currentTarget) return;
            document.getElementById('guideModal').classList.remove('active');
            document.body.style.overflow = '';
        }

        // ESC 키로 모달/메뉴 닫기
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                closeSlideMenu();
                closeGuideModal();
                closeCommunity();
            }
        });

        // =====================================================
        // 커뮤니티 기능
        // =====================================================
        let currentCommunityTab = 'all';
        let communityPage = 1;
        const postsPerPage = 10;

        function openCommunity() {
            document.getElementById('communityModal').classList.add('active');
            document.body.style.overflow = 'hidden';
            closeSlideMenu();
            loadCommunityPosts();
        }

        function closeCommunity(event) {
            if (event && event.target !== event.currentTarget) return;
            document.getElementById('communityModal').classList.remove('active');
            document.body.style.overflow = '';
        }

        function toggleWriteForm() {
            const body = document.querySelector('.write-form-body');
            const arrow = document.querySelector('.write-form-arrow');
            if (body.style.display === 'none') {
                body.style.display = 'flex';
                arrow.style.transform = 'rotate(180deg)';
            } else {
                body.style.display = 'none';
                arrow.style.transform = 'rotate(0deg)';
            }
        }

        function switchCommunityTab(tab) {
            currentCommunityTab = tab;
            communityPage = 1;

            // 탭 UI 업데이트
            document.querySelectorAll('.community-tab').forEach(t => t.classList.remove('active'));
            event.target.classList.add('active');

            loadCommunityPosts();
        }

        async function loadCommunityPosts() {
            const container = document.getElementById('communityPosts');
            container.innerHTML = '<div class="loading-posts">게시글을 불러오는 중...</div>';

            try {
                let url = '/api/community/posts?page=' + communityPage + '&limit=' + postsPerPage;
                if (currentCommunityTab !== 'all') {
                    url += '&category=' + currentCommunityTab;
                }

                const response = await fetch(url);
                const data = await response.json();

                if (data.posts && data.posts.length > 0) {
                    const categoryNames = {
                        'question': '질문',
                        'info': '정보공유',
                        'diary': '성장일기'
                    };

                    container.innerHTML = data.posts.map(post => `
                        <div class="post-item" onclick="viewPost(${post.id})">
                            <span class="post-category ${post.category}">${categoryNames[post.category] || post.category}</span>
                            <div class="post-title">${escapeHtml(post.title)}</div>
                            <div class="post-meta">
                                <span>${post.nickname || '익명'}</span>
                                <span>${formatDate(post.created_at)}</span>
                                <div class="post-stats">
                                    <span>👍 ${post.likes || 0}</span>
                                    <span>💬 ${post.comments || 0}</span>
                                </div>
                            </div>
                        </div>
                    `).join('');

                    // 페이지네이션 렌더링
                    renderPagination(data.total, data.page);
                } else {
                    container.innerHTML = `
                        <div class="no-posts">
                            <p>아직 게시글이 없습니다.</p>
                            <p style="font-size: 12px; margin-top: 8px;">첫 번째 글을 작성해보세요!</p>
                        </div>
                    `;
                }
            } catch (error) {
                console.error('Community load error:', error);
                container.innerHTML = '<div class="no-posts">게시글을 불러올 수 없습니다.</div>';
            }
        }

        function renderPagination(total, currentPage) {
            const container = document.getElementById('communityPagination');
            const totalPages = Math.ceil(total / postsPerPage);

            if (totalPages <= 1) {
                container.innerHTML = '';
                return;
            }

            let html = '';
            for (let i = 1; i <= totalPages; i++) {
                html += `<button class="page-btn ${i === currentPage ? 'active' : ''}" onclick="goToPage(${i})">${i}</button>`;
            }
            container.innerHTML = html;
        }

        function goToPage(page) {
            communityPage = page;
            loadCommunityPosts();
        }

        async function submitPost() {
            const nickname = document.getElementById('postNickname').value.trim() || '익명';
            const category = document.getElementById('postCategory').value;
            const title = document.getElementById('postTitle').value.trim();
            const content = document.getElementById('postContent').value.trim();

            if (!title) {
                alert('제목을 입력해주세요.');
                return;
            }
            if (!content) {
                alert('내용을 입력해주세요.');
                return;
            }

            try {
                const response = await fetch('/api/community/posts', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ nickname, category, title, content })
                });

                const data = await response.json();

                if (data.success) {
                    alert('게시글이 작성되었습니다!');
                    // 폼 초기화
                    document.getElementById('postNickname').value = '';
                    document.getElementById('postTitle').value = '';
                    document.getElementById('postContent').value = '';
                    toggleWriteForm();
                    loadCommunityPosts();
                } else {
                    alert(data.error || '게시글 작성에 실패했습니다.');
                }
            } catch (error) {
                console.error('Submit error:', error);
                alert('게시글 작성 중 오류가 발생했습니다.');
            }
        }

        function viewPost(postId) {
            // 게시글 상세 보기 (추후 구현)
            alert('게시글 상세 보기 기능은 준비 중입니다.');
        }

        function formatDate(dateStr) {
            const date = new Date(dateStr);
            const now = new Date();
            const diff = now - date;

            if (diff < 60000) return '방금 전';
            if (diff < 3600000) return Math.floor(diff / 60000) + '분 전';
            if (diff < 86400000) return Math.floor(diff / 3600000) + '시간 전';
            if (diff < 604800000) return Math.floor(diff / 86400000) + '일 전';

            return date.toLocaleDateString('ko-KR');
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // =====================================================
        // 테마 관리 (다크/라이트 모드)
        // =====================================================
        const THEME_KEY = 'blog_analyzer_theme';

        function toggleTheme() {
            const body = document.body;
            const btn = document.querySelector('.theme-toggle');

            if (body.classList.contains('light-mode')) {
                body.classList.remove('light-mode');
                btn.textContent = '🌙';
                localStorage.setItem(THEME_KEY, 'dark');
            } else {
                body.classList.add('light-mode');
                btn.textContent = '☀️';
                localStorage.setItem(THEME_KEY, 'light');
            }
        }

        function loadTheme() {
            const saved = localStorage.getItem(THEME_KEY);
            const btn = document.querySelector('.theme-toggle');
            if (saved === 'light') {
                document.body.classList.add('light-mode');
                if (btn) btn.textContent = '☀️';
            }
        }

        // 페이지 로드 시 테마 적용
        document.addEventListener('DOMContentLoaded', loadTheme);

        // =====================================================
        // 트렌드 키워드
        // =====================================================
        async function loadTrendKeywords() {
            const container = document.getElementById('trendsList');
            const sourceEl = document.getElementById('trendsSource');
            container.innerHTML = '<span style="color: #ffffff80; font-size: 12px;">로딩 중...</span>';
            sourceEl.textContent = '';
            sourceEl.className = 'trends-source';

            try {
                const response = await fetch('/api/trends');
                const data = await response.json();

                if (data.trends && data.trends.length > 0) {
                    container.innerHTML = data.trends.map((t, idx) => `
                        <div class="trend-item" onclick="copyKeyword('${t.keyword}')" title="클릭하여 복사">
                            <span class="trend-rank">${idx + 1}</span>
                            <span class="trend-keyword">${t.keyword}</span>
                            <span class="trend-category">${t.category}</span>
                        </div>
                    `).join('');

                    // 출처 표시 (숨김)
                    sourceEl.textContent = '';
                    sourceEl.style.display = 'none';
                } else {
                    container.innerHTML = '<span style="color: #ffffff80; font-size: 12px;">트렌드 키워드를 불러올 수 없습니다.</span>';
                }
            } catch (error) {
                container.innerHTML = '<span style="color: #ffffff80; font-size: 12px;">트렌드 로딩 실패</span>';
            }
        }

        // 페이지 로드 시 트렌드 키워드 로드
        document.addEventListener('DOMContentLoaded', loadTrendKeywords);

        // =====================================================
        // PDF 다운로드 기능 (화면 캡처 방식 - 전체 데이터 포함)
        // =====================================================
        let currentAnalysisData = null;

        async function downloadPDF() {
            if (!currentAnalysisData) {
                alert('먼저 블로그를 분석해주세요.');
                return;
            }

            const btn = document.querySelector('.pdf-download-btn');
            const originalText = btn.innerHTML;
            btn.innerHTML = '📄 PDF 생성 중...';
            btn.disabled = true;

            try {
                const data = currentAnalysisData;
                const idx = data.index || {};
                const posts = data.posts_with_index || [];

                // 통계 계산
                const indexed = posts.filter(p => p.exposure === 'indexed').length;
                const missing = posts.filter(p => p.exposure === 'missing').length;
                const avgLikes = posts.length > 0 ? Math.round(posts.reduce((s, p) => s + (p.likes || 0), 0) / posts.length) : 0;
                const avgComments = posts.length > 0 ? Math.round(posts.reduce((s, p) => s + (p.comments || 0), 0) / posts.length) : 0;
                const avgImages = posts.length > 0 ? Math.round(posts.reduce((s, p) => s + (p.images || 0), 0) / posts.length) : 0;
                const avgChars = posts.length > 0 ? Math.round(posts.reduce((s, p) => s + (p.char_count || 0), 0) / posts.length) : 0;
                const exposureRate = posts.length > 0 ? Math.round((indexed / posts.length) * 100) : 0;

                // SEO 점수 계산
                let seoTitle = 0, seoImage = 0, seoContent = 0, seoExposure = 0;
                if (posts.length > 0) {
                    posts.slice(0, 10).forEach(p => {
                        const len = (p.title || '').length;
                        if (len >= 20 && len <= 45) seoTitle += 10;
                        else if (len >= 15 && len <= 50) seoTitle += 5;
                        if (p.keyword && (p.title || '').includes(p.keyword)) seoTitle += 15;

                        const img = p.images || 0;
                        if (img >= 5 && img <= 15) seoImage += 15;
                        else if (img >= 3) seoImage += 10;
                        else if (img > 0) seoImage += 5;

                        const chars = p.char_count || 0;
                        if (chars >= 2000) seoContent += 15;
                        else if (chars >= 1500) seoContent += 10;
                        else if (chars >= 1000) seoContent += 5;
                        if ((p.subheading_count || 0) >= 2) seoContent += 10;
                    });
                    const cnt = Math.min(10, posts.length);
                    seoTitle = Math.round(seoTitle / cnt);
                    seoImage = Math.round(seoImage / cnt);
                    seoContent = Math.round(seoContent / cnt);
                    seoExposure = Math.round((indexed / cnt) * 25);
                }
                const seoTotal = seoTitle + seoImage + seoContent + seoExposure;
                const seoGrade = seoTotal >= 70 ? '우수' : seoTotal >= 50 ? '양호' : seoTotal >= 30 ? '보통' : '개선필요';

                // 포스팅 테이블 HTML 생성
                let postsTableHTML = '';
                posts.forEach((p, i) => {
                    const expColor = p.exposure === 'indexed' ? '#4CAF50' : p.exposure === 'missing' ? '#F44336' : '#FFC107';
                    const expText = p.exposure === 'indexed' ? '노출' : p.exposure === 'missing' ? '누락' : '확인중';
                    postsTableHTML += `
                        <tr style="border-bottom: 1px solid #eee;">
                            <td style="padding: 10px 8px; font-size: 11px; color: #888;">${i + 1}</td>
                            <td style="padding: 10px 8px; font-size: 11px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${(p.title || '').substring(0, 30)}${(p.title || '').length > 30 ? '...' : ''}</td>
                            <td style="padding: 10px 8px; font-size: 11px; color: #667eea;">${p.keyword || '-'}</td>
                            <td style="padding: 10px 8px; font-size: 11px; font-weight: 600; color: ${expColor};">${expText}</td>
                            <td style="padding: 10px 8px; font-size: 11px; text-align: center;">♥${p.likes || 0}</td>
                            <td style="padding: 10px 8px; font-size: 11px; text-align: center;">💬${p.comments || 0}</td>
                            <td style="padding: 10px 8px; font-size: 11px; text-align: center;">${p.images || 0}장</td>
                            <td style="padding: 10px 8px; font-size: 11px; text-align: center;">${(p.char_count || 0).toLocaleString()}자</td>
                        </tr>
                    `;
                });

                // PDF용 임시 HTML 생성
                const pdfContent = document.createElement('div');
                pdfContent.id = 'pdf-export-content';
                pdfContent.style.cssText = 'position: fixed; left: -9999px; top: 0; width: 800px; background: white; padding: 40px; font-family: "Noto Sans KR", sans-serif; color: #333;';

                pdfContent.innerHTML = `
                    <!-- 헤더 -->
                    <div style="text-align: center; margin-bottom: 30px; padding-bottom: 20px; border-bottom: 3px solid #667eea;">
                        <h1 style="color: #667eea; font-size: 28px; margin-bottom: 10px;">📊 블로그 지수 분석 리포트</h1>
                        <p style="color: #888; font-size: 14px;">${new Date().toLocaleDateString('ko-KR')} 분석</p>
                    </div>

                    <!-- 블로그 정보 + 지수 -->
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px;">
                        <div style="background: #f8f9fa; border-radius: 12px; padding: 20px;">
                            <h2 style="color: #333; font-size: 16px; margin-bottom: 12px; border-left: 4px solid #667eea; padding-left: 10px;">블로그 정보</h2>
                            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                                <tr><td style="padding: 6px 0; color: #666;">블로그 ID</td><td style="font-weight: 600;">${data.blog_id}</td></tr>
                                <tr><td style="padding: 6px 0; color: #666;">블로그명</td><td style="font-weight: 600;">${data.blog_name || data.blog_nickname || '-'}</td></tr>
                                <tr><td style="padding: 6px 0; color: #666;">블로그 연차</td><td style="font-weight: 600;">${Math.floor((data.blog_age_days || 0) / 365)}년 ${Math.floor(((data.blog_age_days || 0) % 365) / 30)}개월</td></tr>
                                <tr><td style="padding: 6px 0; color: #666;">총 포스팅</td><td style="font-weight: 600;">${(data.total_posts || 0).toLocaleString()}개</td></tr>
                                <tr><td style="padding: 6px 0; color: #666;">최근 30일 포스팅</td><td style="font-weight: 600;">${data.recent_30days_posts || 0}개</td></tr>
                            </table>
                        </div>
                        <div style="background: #f8f9fa; border-radius: 12px; padding: 20px;">
                            <h2 style="color: #333; font-size: 16px; margin-bottom: 12px; border-left: 4px solid #764ba2; padding-left: 10px;">방문자 & 이웃</h2>
                            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                                <tr><td style="padding: 6px 0; color: #666;">일일 방문자</td><td style="font-weight: 600; color: #667eea;">${(data.daily_visitors || 0).toLocaleString()}명</td></tr>
                                <tr><td style="padding: 6px 0; color: #666;">전체 방문자</td><td style="font-weight: 600;">${(data.total_visitors || 0).toLocaleString()}명</td></tr>
                                <tr><td style="padding: 6px 0; color: #666;">이웃 수</td><td style="font-weight: 600;">${(data.neighbors || 0).toLocaleString()}명</td></tr>
                                <tr><td style="padding: 6px 0; color: #666;">평균 공감</td><td style="font-weight: 600; color: #F44336;">${avgLikes}개</td></tr>
                                <tr><td style="padding: 6px 0; color: #666;">평균 댓글</td><td style="font-weight: 600; color: #2196F3;">${avgComments}개</td></tr>
                            </table>
                        </div>
                    </div>

                    <!-- 블로그 지수 -->
                    <div style="background: linear-gradient(135deg, #667eea15 0%, #764ba215 100%); border: 2px solid #667eea40; border-radius: 12px; padding: 24px; margin-bottom: 24px;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div>
                                <h2 style="color: #333; font-size: 16px; margin-bottom: 8px;">블로그 지수</h2>
                                <div style="font-size: 48px; font-weight: 800; color: ${idx.color || '#667eea'};">${idx.grade || '-'}</div>
                                <div style="font-size: 18px; color: #667eea; margin-top: 4px;">${idx.score || 0} / 100점</div>
                            </div>
                            <div style="display: flex; gap: 24px; text-align: center;">
                                <div style="background: white; padding: 16px 24px; border-radius: 10px;">
                                    <div style="color: #888; font-size: 11px;">노출 지수</div>
                                    <div style="font-size: 24px; font-weight: 700; color: #667eea;">${idx.breakdown?.exposure || 0}</div>
                                    <div style="font-size: 10px; color: #aaa;">/ 100 (70%)</div>
                                </div>
                                <div style="background: white; padding: 16px 24px; border-radius: 10px;">
                                    <div style="color: #888; font-size: 11px;">활동 지수</div>
                                    <div style="font-size: 24px; font-weight: 700; color: #764ba2;">${idx.breakdown?.activity || 0}</div>
                                    <div style="font-size: 10px; color: #aaa;">/ 100 (15%)</div>
                                </div>
                                <div style="background: white; padding: 16px 24px; border-radius: 10px;">
                                    <div style="color: #888; font-size: 11px;">신뢰 지수</div>
                                    <div style="font-size: 24px; font-weight: 700; color: #00C853;">${idx.breakdown?.trust || 0}</div>
                                    <div style="font-size: 10px; color: #aaa;">/ 100 (15%)</div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- SEO 점수 -->
                    <div style="background: #f8f9fa; border-radius: 12px; padding: 20px; margin-bottom: 24px;">
                        <h2 style="color: #333; font-size: 16px; margin-bottom: 16px; border-left: 4px solid #00C853; padding-left: 10px;">SEO 점수 분석 - ${seoTotal}/100점 (${seoGrade})</h2>
                        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; text-align: center;">
                            <div style="background: white; padding: 14px; border-radius: 8px; border: 1px solid #eee;">
                                <div style="color: #888; font-size: 11px;">제목 SEO</div>
                                <div style="font-size: 20px; font-weight: 700; color: #667eea;">${seoTitle}/25</div>
                            </div>
                            <div style="background: white; padding: 14px; border-radius: 8px; border: 1px solid #eee;">
                                <div style="color: #888; font-size: 11px;">이미지 SEO</div>
                                <div style="font-size: 20px; font-weight: 700; color: #764ba2;">${seoImage}/25</div>
                            </div>
                            <div style="background: white; padding: 14px; border-radius: 8px; border: 1px solid #eee;">
                                <div style="color: #888; font-size: 11px;">콘텐츠 SEO</div>
                                <div style="font-size: 20px; font-weight: 700; color: #FF9800;">${seoContent}/25</div>
                            </div>
                            <div style="background: white; padding: 14px; border-radius: 8px; border: 1px solid #eee;">
                                <div style="color: #888; font-size: 11px;">노출 SEO</div>
                                <div style="font-size: 20px; font-weight: 700; color: #4CAF50;">${seoExposure}/25</div>
                            </div>
                        </div>
                    </div>

                    <!-- 포스팅 분석 요약 -->
                    <div style="background: #f8f9fa; border-radius: 12px; padding: 20px; margin-bottom: 24px;">
                        <h2 style="color: #333; font-size: 16px; margin-bottom: 16px; border-left: 4px solid #F44336; padding-left: 10px;">포스팅 분석 요약 (최근 ${posts.length}개)</h2>
                        <div style="display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; text-align: center;">
                            <div style="background: white; padding: 14px; border-radius: 8px; border: 1px solid #eee;">
                                <div style="color: #888; font-size: 11px;">검색 노출률</div>
                                <div style="font-size: 22px; font-weight: 700; color: ${exposureRate >= 50 ? '#4CAF50' : '#FFC107'};">${exposureRate}%</div>
                            </div>
                            <div style="background: white; padding: 14px; border-radius: 8px; border: 1px solid #eee;">
                                <div style="color: #888; font-size: 11px;">노출 / 누락</div>
                                <div style="font-size: 18px; font-weight: 700;"><span style="color: #4CAF50;">${indexed}</span> / <span style="color: #F44336;">${missing}</span></div>
                            </div>
                            <div style="background: white; padding: 14px; border-radius: 8px; border: 1px solid #eee;">
                                <div style="color: #888; font-size: 11px;">평균 이미지</div>
                                <div style="font-size: 22px; font-weight: 700; color: #667eea;">${avgImages}장</div>
                            </div>
                            <div style="background: white; padding: 14px; border-radius: 8px; border: 1px solid #eee;">
                                <div style="color: #888; font-size: 11px;">평균 글자수</div>
                                <div style="font-size: 18px; font-weight: 700; color: #764ba2;">${avgChars.toLocaleString()}자</div>
                            </div>
                            <div style="background: white; padding: 14px; border-radius: 8px; border: 1px solid #eee;">
                                <div style="color: #888; font-size: 11px;">평균 반응</div>
                                <div style="font-size: 18px; font-weight: 700; color: #FF5722;">${avgLikes + avgComments}개</div>
                            </div>
                        </div>
                    </div>

                    <!-- 포스팅 상세 목록 -->
                    <div style="background: #f8f9fa; border-radius: 12px; padding: 20px; margin-bottom: 24px;">
                        <h2 style="color: #333; font-size: 16px; margin-bottom: 16px; border-left: 4px solid #2196F3; padding-left: 10px;">포스팅 상세 목록</h2>
                        <table style="width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden;">
                            <thead>
                                <tr style="background: #667eea; color: white;">
                                    <th style="padding: 10px 8px; font-size: 11px; font-weight: 600;">#</th>
                                    <th style="padding: 10px 8px; font-size: 11px; font-weight: 600; text-align: left;">제목</th>
                                    <th style="padding: 10px 8px; font-size: 11px; font-weight: 600;">키워드</th>
                                    <th style="padding: 10px 8px; font-size: 11px; font-weight: 600;">노출</th>
                                    <th style="padding: 10px 8px; font-size: 11px; font-weight: 600;">공감</th>
                                    <th style="padding: 10px 8px; font-size: 11px; font-weight: 600;">댓글</th>
                                    <th style="padding: 10px 8px; font-size: 11px; font-weight: 600;">이미지</th>
                                    <th style="padding: 10px 8px; font-size: 11px; font-weight: 600;">글자수</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${postsTableHTML}
                            </tbody>
                        </table>
                    </div>

                    <!-- 푸터 -->
                    <div style="text-align: center; color: #aaa; font-size: 11px; margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee;">
                        Generated by 블로그 지수 분석기 | ${new Date().toLocaleString('ko-KR')}<br>
                        <span style="font-size: 10px;">이 리포트는 공개된 데이터를 기반으로 자체 알고리즘으로 분석한 결과입니다.</span>
                    </div>
                `;

                document.body.appendChild(pdfContent);

                // html2canvas로 캡처
                const canvas = await html2canvas(pdfContent, {
                    scale: 2,
                    useCORS: true,
                    logging: false,
                    backgroundColor: '#ffffff'
                });

                // PDF 생성 (여러 페이지 지원)
                const { jsPDF } = window.jspdf;
                const pdf = new jsPDF('p', 'mm', 'a4');

                const pageWidth = 210;
                const pageHeight = 297;
                const imgWidth = pageWidth;
                const imgHeight = (canvas.height * imgWidth) / canvas.width;

                let heightLeft = imgHeight;
                let position = 0;

                // 첫 페이지
                pdf.addImage(canvas.toDataURL('image/png'), 'PNG', 0, position, imgWidth, imgHeight);
                heightLeft -= pageHeight;

                // 추가 페이지 (필요시)
                while (heightLeft > 0) {
                    position = heightLeft - imgHeight;
                    pdf.addPage();
                    pdf.addImage(canvas.toDataURL('image/png'), 'PNG', 0, position, imgWidth, imgHeight);
                    heightLeft -= pageHeight;
                }

                // 다운로드
                pdf.save('블로그분석_' + data.blog_id + '_' + new Date().toISOString().split('T')[0] + '.pdf');

                // 임시 요소 제거
                document.body.removeChild(pdfContent);

            } catch (error) {
                console.error('PDF 생성 오류:', error);
                alert('PDF 생성 중 오류가 발생했습니다: ' + error.message);
            } finally {
                btn.innerHTML = originalText;
                btn.disabled = false;
            }
        }

        // =====================================================
        // 히스토리 비교 기능
        // =====================================================
        const FULL_HISTORY_KEY = 'blog_analyzer_full_history';

        function saveFullHistory(data) {
            try {
                const history = JSON.parse(localStorage.getItem(FULL_HISTORY_KEY) || '{}');
                const blogId = data.blog_id;

                if (!history[blogId]) {
                    history[blogId] = [];
                }

                history[blogId].unshift({
                    date: new Date().toISOString(),
                    score: data.index?.score || 0,
                    grade: data.index?.grade || '-',
                    daily_visitors: data.daily_visitors || 0,
                    total_visitors: data.total_visitors || 0,
                    neighbors: data.neighbors || 0,
                    total_posts: data.total_posts || 0,
                    recent_30days_posts: data.recent_30days_posts || 0,
                    exposure_breakdown: data.index?.breakdown?.exposure || 0,
                    activity_breakdown: data.index?.breakdown?.activity || 0,
                    trust_breakdown: data.index?.breakdown?.trust || 0
                });

                // 최대 10개 유지
                history[blogId] = history[blogId].slice(0, 10);

                localStorage.setItem(FULL_HISTORY_KEY, JSON.stringify(history));
            } catch (e) {
                console.warn('Full history save failed:', e);
            }
        }

        function getCompareData(blogId) {
            try {
                const history = JSON.parse(localStorage.getItem(FULL_HISTORY_KEY) || '{}');
                return history[blogId] || [];
            } catch (e) {
                return [];
            }
        }

        function getWeeklyAverage(blogId) {
            try {
                const history = JSON.parse(localStorage.getItem(FULL_HISTORY_KEY) || '{}');
                const entries = history[blogId] || [];

                if (entries.length === 0) return null;

                // 오늘 날짜 (당일 제외용)
                const now = new Date();
                const today = `${now.getFullYear()}-${now.getMonth()}-${now.getDate()}`;

                // 7일 전 날짜
                const sevenDaysAgo = new Date(now - 7 * 24 * 60 * 60 * 1000);

                // 당일 제외 + 최근 7일 데이터만 사용
                const recentEntries = entries.filter(e => {
                    const d = new Date(e.date);
                    const dateKey = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
                    return dateKey !== today && d >= sevenDaysAgo;
                });

                if (recentEntries.length === 0) return null;

                // 고유한 날짜 수 계산 (하루에 여러번 분석해도 1일로 계산)
                const uniqueDays = new Set(recentEntries.map(e => {
                    const d = new Date(e.date);
                    return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
                }));
                const dayCount = Math.min(uniqueDays.size, 7);  // 최대 7일

                // 날짜별 최신 데이터만 사용하여 평균 계산
                const dailyData = {};
                recentEntries.forEach(e => {
                    const d = new Date(e.date);
                    const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
                    if (!dailyData[key] || new Date(e.date) > new Date(dailyData[key].date)) {
                        dailyData[key] = e;
                    }
                });

                const dailyValues = Object.values(dailyData);
                const sum = dailyValues.reduce((acc, e) => acc + (e.daily_visitors || 0), 0);
                const avg = Math.round(sum / dailyValues.length);

                return {
                    average: avg,
                    count: dayCount,  // 고유 날짜 수 (최대 7, 당일 제외)
                    max: Math.max(...dailyValues.map(e => e.daily_visitors || 0)),
                    min: Math.min(...dailyValues.map(e => e.daily_visitors || 0))
                };
            } catch (e) {
                console.warn('Weekly average calculation failed:', e);
                return null;
            }
        }

        function showHistoryData() {
            const h = JSON.parse(localStorage.getItem(FULL_HISTORY_KEY) || '{}');
            let msg = '=== 저장된 히스토리 ===\\n\\n';

            if (Object.keys(h).length === 0) {
                alert('저장된 히스토리가 없습니다.');
                return;
            }

            Object.keys(h).forEach(function(blogId) {
                msg += '📌 ' + blogId + ':\\n';
                h[blogId].forEach(function(e, i) {
                    const date = e.date ? e.date.split('T')[0] : '날짜없음';
                    msg += '  ' + (i+1) + '. ' + date + ' - 방문자: ' + (e.daily_visitors || 0) + '명\\n';
                });
                msg += '\\n';
            });

            alert(msg);
        }

        function showCompareModal() {
            if (!currentAnalysisData) {
                alert('먼저 블로그를 분석해주세요.');
                return;
            }

            const blogId = currentAnalysisData.blog_id;
            const history = getCompareData(blogId);

            if (history.length < 2) {
                alert('비교할 이전 기록이 없습니다. 같은 블로그를 다시 분석하면 비교가 가능합니다.');
                return;
            }

            const current = history[0];
            const previous = history[1];

            function getDiff(cur, prev) {
                const diff = cur - prev;
                if (diff > 0) return { value: '+' + diff.toLocaleString(), class: 'positive' };
                if (diff < 0) return { value: diff.toLocaleString(), class: 'negative' };
                return { value: '0', class: 'neutral' };
            }

            const comparisons = [
                { label: '종합 점수', old: previous.score, new: current.score },
                { label: '등급', old: previous.grade, new: current.grade },
                { label: '일일 방문자', old: previous.daily_visitors, new: current.daily_visitors },
                { label: '전체 방문자', old: previous.total_visitors, new: current.total_visitors },
                { label: '이웃 수', old: previous.neighbors, new: current.neighbors },
                { label: '총 포스팅', old: previous.total_posts, new: current.total_posts },
                { label: '노출 지수', old: previous.exposure_breakdown, new: current.exposure_breakdown },
                { label: '활동 지수', old: previous.activity_breakdown, new: current.activity_breakdown },
            ];

            let html = '<div class="compare-result">';
            html += '<div style="margin-bottom: 12px; font-size: 12px; color: #ffffff80;">';
            html += '이전 분석: ' + new Date(previous.date).toLocaleDateString('ko-KR');
            html += ' → 현재: ' + new Date(current.date).toLocaleDateString('ko-KR');
            html += '</div>';

            comparisons.forEach(c => {
                const diff = typeof c.old === 'number' ? getDiff(c.new, c.old) : { value: c.old === c.new ? '=' : 'changed', class: 'neutral' };
                html += '<div class="compare-row">';
                html += '<span class="compare-label">' + c.label + '</span>';
                html += '<span class="compare-old">' + (typeof c.old === 'number' ? c.old.toLocaleString() : c.old) + '</span>';
                html += '<span class="compare-new">' + (typeof c.new === 'number' ? c.new.toLocaleString() : c.new) + '</span>';
                html += '<span class="compare-diff ' + diff.class + '">' + diff.value + '</span>';
                html += '</div>';
            });

            html += '</div>';

            // 모달 표시
            const modal = document.getElementById('analysisModal');
            const body = document.getElementById('analysisModalBody');
            document.querySelector('#analysisModal .modal-header h3').textContent = '📊 이전 분석과 비교';
            body.innerHTML = html;
            modal.classList.add('active');
        }

        // =====================================================
        // 경쟁 블로그 분석
        // =====================================================
        async function analyzeCompetitor(keyword) {
            if (!currentAnalysisData || !keyword) return;

            try {
                const response = await fetch(`/api/competitor?keyword=${encodeURIComponent(keyword)}&blog_id=${currentAnalysisData.blog_id}`);
                const data = await response.json();

                if (data.competitors && data.competitors.length > 0) {
                    let html = '<div class="competitor-list">';
                    data.competitors.forEach(c => {
                        html += '<div class="competitor-item ' + (c.is_mine ? 'is-mine' : '') + '">';
                        html += '<div class="competitor-rank">' + c.rank + '</div>';
                        html += '<div class="competitor-info">';
                        html += '<div class="competitor-title">' + c.title + '</div>';
                        html += '<div class="competitor-id">' + c.blog_id + (c.is_mine ? ' (내 블로그)' : '') + '</div>';
                        html += '</div>';
                        html += '<a href="' + c.link + '" target="_blank" class="competitor-link">보기 →</a>';
                        html += '</div>';
                    });
                    html += '</div>';

                    if (data.my_rank) {
                        html = '<div style="text-align: center; margin-bottom: 16px; padding: 12px; background: #00c8531a; border-radius: 10px;">🎉 내 블로그가 <strong style="color: #00C853;">' + data.my_rank + '위</strong>에 있습니다!</div>' + html;
                    } else {
                        html = '<div style="text-align: center; margin-bottom: 16px; padding: 12px; background: #ffc1071a; border-radius: 10px;">⚠️ 내 블로그가 상위 5개 결과에 없습니다</div>' + html;
                    }

                    return html;
                }
            } catch (error) {
                console.error('Competitor analysis error:', error);
            }
            return '';
        }

        // =====================================================
        // 히스토리 관리 (LocalStorage)
        // =====================================================
        const HISTORY_KEY = 'blog_analyzer_history';
        const MAX_HISTORY = 10;

        function loadHistory() {
            try {
                return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
            } catch (e) {
                return [];
            }
        }

        function saveToHistory(data) {
            try {
                const history = loadHistory();
                const newItem = {
                    blog_id: data.blog_id,
                    blog_name: data.blog_name || data.blog_nickname || data.blog_id,
                    grade: data.index?.grade || '-',
                    score: data.index?.score || 0,
                    color: data.index?.color || '#9E9E9E',
                    date: new Date().toISOString().split('T')[0],
                    timestamp: Date.now()
                };

                // 중복 제거 후 맨 앞에 추가
                const filtered = history.filter(h => h.blog_id !== data.blog_id);
                filtered.unshift(newItem);

                // 최대 개수 제한
                const limited = filtered.slice(0, MAX_HISTORY);
                localStorage.setItem(HISTORY_KEY, JSON.stringify(limited));

                renderHistory();

                // Supabase DB에도 저장
                saveToSupabase(data);
            } catch (e) {
                console.warn('히스토리 저장 실패:', e);
            }
        }

        // Supabase DB 저장 함수
        async function saveToSupabase(data) {
            try {
                const response = await fetch('/api/history/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        blog_id: data.blog_id,
                        analysis_data: data
                    })
                });
                const result = await response.json();
                if (result.success) {
                    console.log('✅ DB 저장 완료:', data.blog_id);
                }
            } catch (e) {
                console.warn('DB 저장 실패:', e);
            }
        }

        function deleteHistoryItem(blogId, event) {
            event.stopPropagation();
            try {
                const history = loadHistory();
                const filtered = history.filter(h => h.blog_id !== blogId);
                localStorage.setItem(HISTORY_KEY, JSON.stringify(filtered));
                renderHistory();
            } catch (e) {
                console.warn('히스토리 삭제 실패:', e);
            }
        }

        function clearHistory() {
            if (confirm('모든 분석 기록을 삭제하시겠습니까?')) {
                localStorage.removeItem(HISTORY_KEY);
                renderHistory();
            }
        }

        function renderHistory() {
            const history = loadHistory();
            const section = document.getElementById('historySection');
            const list = document.getElementById('historyList');

            if (history.length === 0) {
                section.style.display = 'none';
                return;
            }

            section.style.display = 'block';
            list.innerHTML = history.map(item => `
                <div class="history-item" onclick="loadFromHistory('${item.blog_id}')">
                    <span class="history-item-name">${item.blog_name}</span>
                    <span class="history-item-grade" style="background: ${item.color}22; color: ${item.color}">${item.grade}</span>
                    <span class="history-item-date">${item.date}</span>
                    <span class="history-item-delete" onclick="deleteHistoryItem('${item.blog_id}', event)">&times;</span>
                </div>
            `).join('');
        }

        function loadFromHistory(blogId) {
            document.getElementById('blogId').value = blogId;
            document.querySelector('.search-form').dispatchEvent(new Event('submit'));
        }

        // 페이지 로드 시 히스토리 렌더링
        document.addEventListener('DOMContentLoaded', renderHistory);

        // =====================================================
        // 키워드 추천 (네이버 자동완성 API)
        // =====================================================
        async function getKeywordSuggestions() {
            const keyword = document.getElementById('keywordInput').value.trim();
            const resultsDiv = document.getElementById('suggestResults');
            const tagsDiv = document.getElementById('suggestTags');

            if (!keyword) {
                alert('키워드를 입력해주세요.');
                return;
            }

            try {
                // 네이버 검색 자동완성 API (CORS 우회를 위해 백엔드 사용)
                const response = await fetch(`/api/suggest?keyword=${encodeURIComponent(keyword)}`);
                const data = await response.json();

                if (data.suggestions && data.suggestions.length > 0) {
                    tagsDiv.innerHTML = data.suggestions.map(s => `
                        <span class="suggest-tag" onclick="copyKeyword('${s}')" title="클릭하여 복사">${s}</span>
                    `).join('');
                    resultsDiv.classList.add('show');
                } else {
                    tagsDiv.innerHTML = '<span style="color: #ffffff80; font-size: 12px;">연관 키워드를 찾을 수 없습니다.</span>';
                    resultsDiv.classList.add('show');
                }
            } catch (error) {
                tagsDiv.innerHTML = '<span style="color: #ff6b6b; font-size: 12px;">키워드 검색 중 오류가 발생했습니다.</span>';
                resultsDiv.classList.add('show');
            }
        }

        function copyKeyword(keyword) {
            navigator.clipboard.writeText(keyword).then(() => {
                // 임시 토스트 메시지
                const toast = document.createElement('div');
                toast.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#667eea;color:#fff;padding:12px 24px;border-radius:8px;font-size:13px;z-index:10000;';
                toast.textContent = `"${keyword}" 복사됨`;
                document.body.appendChild(toast);
                setTimeout(() => toast.remove(), 2000);
            });
        }

        // 키워드 입력시 Enter 키 지원
        document.addEventListener('DOMContentLoaded', () => {
            document.getElementById('keywordInput').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    getKeywordSuggestions();
                }
            });
        });

        // =====================================================
        // 블로그 분석 관련 함수들
        // =====================================================

        // 블로그 URL 생성 함수
        function getBlogUrl(data) {
            return 'https://blog.naver.com/' + data.blog_id;
        }

        // 블로그 표시 URL 생성 함수
        function getBlogDisplayUrl(data) {
            return 'blog.naver.com/' + data.blog_id;
        }

        async function analyzeBlog(e) {
            e.preventDefault();

            const blogId = document.getElementById('blogId').value.trim();
            const resultDiv = document.getElementById('result');
            const searchBtn = document.getElementById('searchBtn');

            if (!blogId) {
                resultDiv.innerHTML = '<div class="error">⚠️ 블로그 아이디를 입력해주세요.</div>';
                return;
            }

            // 로딩 표시
            searchBtn.disabled = true;
            searchBtn.innerHTML = '⏳ 분석 중...';
            resultDiv.innerHTML = `
                <div class="loading">
                    <div class="spinner"></div>
                    <p>블로그 데이터를 분석하고 있습니다...</p>
                    <p style="font-size: 12px; color: #ffffff66; margin-top: 8px;">포스팅 지수 분석 중 (약 1분~1분 30초 소요)</p>
                </div>
            `;

            try {
                // 주간 평균 계산해서 서버로 전송 (최소 3일 이상 데이터 필요)
                const weeklyAvg = getWeeklyAverage(blogId);
                let url = `/api/analyze?blog_id=${encodeURIComponent(blogId)}`;
                if (weeklyAvg && weeklyAvg.count >= 3) {
                    url += `&weekly_avg=${weeklyAvg.average}&weekly_count=${weeklyAvg.count}`;
                }

                const response = await fetch(url);
                const data = await response.json();
                
                if (data.error) {
                    resultDiv.innerHTML = `<div class="error">⚠️ ${data.error}</div>`;
                } else {
                    displayResult(data);
                    saveToHistory(data);  // 히스토리에 저장
                }
            } catch (error) {
                resultDiv.innerHTML = `<div class="error">⚠️ 서버 오류가 발생했습니다: ${error.message}</div>`;
            } finally {
                searchBtn.disabled = false;
                searchBtn.innerHTML = '🔍 분석하기';
            }
        }

        // 노출 상태 뱃지 생성
        function getExposureBadge(exposure) {
            const badges = {
                'indexed': '<span class="exposure-badge exposure-indexed">노출 🔍</span>',
                'pending': '<span class="exposure-badge exposure-pending">반영예정</span>',
                'missing': '<span class="exposure-badge exposure-missing">누락</span>',
                'unknown': '<span class="exposure-badge exposure-pending">확인중</span>'
            };
            return badges[exposure] || badges['unknown'];
        }

        // 키워드 경쟁도 추정 (키워드 길이 기반 간단 추정)
        function getCompetitionBadge(keyword) {
            if (!keyword) return '';

            const wordCount = keyword.split(' ').length;
            const charCount = keyword.length;

            // 롱테일 키워드 (3단어 이상 또는 15자 이상) = 낮은 경쟁
            if (wordCount >= 3 || charCount >= 15) {
                return '<span class="competition-badge competition-low">경쟁↓</span>';
            }
            // 중간 키워드 (2단어 또는 8~14자)
            else if (wordCount === 2 || charCount >= 8) {
                return '<span class="competition-badge competition-medium">경쟁중</span>';
            }
            // 짧은 키워드 (1단어, 7자 이하) = 높은 경쟁
            else {
                return '<span class="competition-badge competition-high">경쟁↑</span>';
            }
        }

        // 날짜 포맷팅
        function formatDate(dateStr) {
            if (!dateStr) return '-';
            try {
                // "Wed, 31 Dec 2025 14:04:41 +0900" 형식 파싱
                const date = new Date(dateStr);
                if (isNaN(date.getTime())) return dateStr.substring(0, 16);
                return date.toISOString().split('T')[0];  // YYYY-MM-DD
            } catch (e) {
                return dateStr.substring(0, 16);
            }
        }

        // 상대 날짜 포맷팅 (X시간 전, X일 전)
        function formatRelativeDate(dateStr) {
            if (!dateStr) return '-';
            try {
                const date = new Date(dateStr);
                if (isNaN(date.getTime())) return '-';

                const now = new Date();
                const diffMs = now - date;
                const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
                const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

                if (diffHours < 1) return '방금 전';
                if (diffHours < 24) return diffHours + '시간 전';
                if (diffDays < 7) return diffDays + '일 전';
                if (diffDays < 30) return Math.floor(diffDays / 7) + '주 전';
                return Math.floor(diffDays / 30) + '개월 전';
            } catch (e) {
                return '-';
            }
        }

        // 콘텐츠 지수 계산 (0~1) - 정확한 평가 버전
        function calculateContentIndex(post) {
            if (!post) return -1;

            let score = 0;
            let maxScore = 100;

            // 1. 제목 길이 점수 (최대 15점) - 20~45자가 최적
            const titleLen = (post.title || '').length;
            let titleScore = 0;
            if (titleLen >= 20 && titleLen <= 45) titleScore = 15;        // 최적
            else if (titleLen >= 15 && titleLen <= 50) titleScore = 12;   // 좋음
            else if (titleLen >= 10 && titleLen <= 60) titleScore = 8;    // 보통
            else if (titleLen >= 5) titleScore = 4;                        // 짧음
            score += titleScore;

            // 2. 이미지 수 점수 (최대 20점) - 5~15장이 최적
            const images = post.images || 0;
            let imageScore = 0;
            if (images >= 5 && images <= 15) imageScore = 20;             // 최적
            else if (images >= 3 && images <= 20) imageScore = 15;        // 좋음
            else if (images >= 1 && images <= 25) imageScore = 10;        // 보통
            else if (images > 25) imageScore = 5;                          // 너무 많음
            // 0장이면 0점
            score += imageScore;

            // 3. 글자 수 점수 (최대 25점) - 1500자 이상이 최적
            const charCount = post.char_count || 0;
            let charScore = 0;
            if (charCount >= 2000) charScore = 25;                         // 최적
            else if (charCount >= 1500) charScore = 22;                    // 매우 좋음
            else if (charCount >= 1200) charScore = 18;                    // 좋음
            else if (charCount >= 1000) charScore = 14;                    // 적정
            else if (charCount >= 700) charScore = 10;                     // 보통
            else if (charCount >= 400) charScore = 6;                      // 짧음
            else if (charCount > 0) charScore = 3;                         // 매우 짧음
            // 0이면 0점 (데이터 수집 실패 시)
            score += charScore;

            // 4. 노출 여부 점수 (최대 25점)
            let exposureScore = 0;
            if (post.exposure === 'indexed') exposureScore = 25;          // 검색 노출됨
            else if (post.exposure === 'pending') exposureScore = 12;     // 대기중/확인중
            // missing이면 0점
            score += exposureScore;

            // 5. 반응 점수 - 공감+댓글 (최대 15점)
            const likes = post.likes || 0;
            const comments = post.comments || 0;
            const engagement = likes + comments;
            let engageScore = 0;
            if (engagement >= 20) engageScore = 15;                        // 인기글
            else if (engagement >= 10) engageScore = 12;                   // 좋음
            else if (engagement >= 5) engageScore = 8;                     // 보통
            else if (engagement >= 2) engageScore = 5;                     // 약간
            else if (engagement >= 1) engageScore = 2;                     // 있음
            // 0이면 0점
            score += engageScore;

            // 총점 100점 만점 -> 0~1 비율로 변환
            return score / maxScore;
        }

        // 형태소 분석 (제목에서 키워드 추출)
        function getMorphemeAnalysis(posts) {
            if (!posts || posts.length === 0) return [];

            const wordCount = {};
            const stopwords = ['그리고', '하지만', '그래서', '또한', '하는', '있는', '없는', '되는', '이런', '저런', '어떤', '모든', '같은', '다른', '우리', '나의', '통해', '위해', '대한', '관한', '에서', '으로', '에게'];

            posts.forEach(function(post) {
                const title = post.title || '';
                // 한글 2글자 이상, 영문 3글자 이상 추출
                const words = title.match(/[가-힣]{2,}|[a-zA-Z]{3,}/g) || [];

                words.forEach(function(word) {
                    const w = word.toLowerCase();
                    if (!stopwords.includes(w) && w.length >= 2) {
                        wordCount[word] = (wordCount[word] || 0) + 1;
                    }
                });
            });

            // 빈도순 정렬
            const sorted = Object.keys(wordCount).map(function(word) {
                return { word: word, count: wordCount[word] };
            }).sort(function(a, b) {
                return b.count - a.count;
            });

            return sorted;
        }

        // HTML 속성 이스케이핑 함수 (전역)
        function escapeHtmlAttr(str) {
            return String(str || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        }

        // 개별 포스트 키워드 추출 함수 (개선된 버전)
        function getPostKeywords(post, maxKeywords) {
            maxKeywords = maxKeywords || 3;
            const title = (post && post.title) || '';
            if (!title) return [];

            // 불용어 (조사, 어미, 접속사 등)
            const stopwords = ['그리고', '하지만', '그래서', '또한', '그런', '이런', '저런', '어떤', '모든', '같은', '다른', '우리', '나의', '통해', '위해', '대한', '관한', '에서', '으로', '에게', '했다', '한다', '입니다', '합니다', '있다', '없다', '이다', '했습니다', '하기', '되기', '보기', '알아', '해요', '에요', '군요', '네요', '아요', '어요', '구나', '는데', '니다', '습니다', '어서', '니까', '지만', '라서', '려고', '면서', '든지', '거나', '듯이'];

            // 동사/형용사 어미 패턴
            const verbEndings = ['하는', '되는', '있는', '없는', '나는', '오는', '가는', '보는', '주는', '받는', '하고', '되고', '보고', '나고', '하면', '되면', '보면', '오면', '가면', '해서', '해도', '하게', '하니', '해야', '했던', '됐던', '봤던'];

            // 조사 제거 함수
            function removeParticles(word) {
                const particles = ['은', '는', '이', '가', '을', '를', '에', '의', '와', '과', '로', '으로', '에서', '에게', '한테', '께', '도', '만', '까지', '부터', '처럼', '같이', '보다', '라고', '이라고', '라는', '이라는', '에서의', '으로의', '에게서'];
                let result = word;
                for (let p of particles) {
                    if (result.endsWith(p) && result.length > p.length + 1) {
                        result = result.slice(0, -p.length);
                        break;
                    }
                }
                return result;
            }

            // 한글 1글자 이상 추출 (공백으로 분리 후)
            const rawWords = title.split(/[\s,.\-_!?~·:;'"()[\]{}/<>]+/).filter(w => w.length > 0);

            const uniqueWords = [];
            const seen = {};

            rawWords.forEach(function(rawWord) {
                // 한글만 추출
                const koreanMatch = rawWord.match(/[가-힣]+/g);
                if (!koreanMatch) return;

                koreanMatch.forEach(function(word) {
                    // 동사 어미 체크
                    if (verbEndings.some(e => word.endsWith(e) || word === e)) return;

                    // 조사 제거
                    let cleanWord = removeParticles(word);

                    // 불용어 체크
                    if (stopwords.includes(cleanWord)) return;

                    // 1글자는 의미있는 단어만 (명사)
                    if (cleanWord.length === 1) {
                        const singleCharNouns = ['용', '꿈', '집', '차', '밤', '낮', '봄', '여름', '가을', '겨울', '해', '달', '별', '산', '강', '바다', '숲', '꽃', '풀', '나무', '돈', '일', '말', '글', '책', '영화', '음악', '사진', '그림', '옷', '신발', '가방', '맛', '향', '색', '빛', '소리', '힘', '눈', '코', '입', '귀', '손', '발', '머리', '몸', '마음', '사랑', '행복', '슬픔', '기쁨', '화', '죽음', '삶', '병', '약', '술', '밥', '국', '떡', '과일', '고기', '생선', '새', '개', '고양이', '말', '소', '돼지', '닭', '물고기', '뱀', '호랑이', '사자', '곰', '토끼', '쥐'];
                        if (!singleCharNouns.includes(cleanWord)) return;
                    }

                    const w = cleanWord.toLowerCase();
                    if (!seen[w] && cleanWord.length >= 1) {
                        seen[w] = true;
                        uniqueWords.push(cleanWord);
                    }
                });

                // 영문 3글자 이상도 추출
                const englishMatch = rawWord.match(/[a-zA-Z]{3,}/g);
                if (englishMatch) {
                    englishMatch.forEach(function(word) {
                        const w = word.toLowerCase();
                        if (!seen[w]) {
                            seen[w] = true;
                            uniqueWords.push(word);
                        }
                    });
                }
            });

            // 긴 단어 우선
            uniqueWords.sort(function(a, b) {
                return b.length - a.length;
            });

            return uniqueWords.slice(0, maxKeywords);
        }

        // 블로그 코칭 함수들
        function generateDiagnosis(data) {
            const idx = data.index || {};
            const grade = idx.grade || '분석중';
            const score = idx.score || 0;
            const dailyVisitors = data.daily_visitors || 0;
            const recentPosts = data.recent_30days_posts || 0;
            const neighbors = data.neighbors || 0;
            const posts = data.posts_with_index || [];

            // 통계 계산
            const avgImages = posts.length > 0 ? Math.round(posts.reduce((sum, p) => sum + (p.images || 0), 0) / posts.length) : 0;
            const avgTitleLength = posts.length > 0 ? Math.round(posts.reduce((sum, p) => sum + (p.title?.length || 0), 0) / posts.length) : 0;
            const indexed = posts.filter(p => p.exposure === 'indexed').length;
            const indexRate = posts.length > 0 ? Math.round((indexed / posts.length) * 100) : 0;
            const totalLikes = posts.reduce((sum, p) => sum + (p.likes || 0), 0);
            const totalComments = posts.reduce((sum, p) => sum + (p.comments || 0), 0);
            const avgEngagement = posts.length > 0 ? Math.round((totalLikes + totalComments) / posts.length) : 0;

            // 좋은점 (유지해야 할 점)
            let goodPoints = [];

            // 등급 관련
            if (score >= 80) {
                goodPoints.push('상위권 블로그 등급(' + grade + ')을 유지하고 있습니다. 현재 전략을 유지하세요.');
            } else if (score >= 60) {
                goodPoints.push('중상위 등급(' + grade + ')으로 성장 가능성이 높습니다.');
            }

            // 방문자 관련
            if (dailyVisitors >= 1000) {
                goodPoints.push('일일 방문자 ' + dailyVisitors.toLocaleString() + '명은 매우 훌륭한 수치입니다. 꾸준히 유지하세요!');
            } else if (dailyVisitors >= 500) {
                goodPoints.push('일일 방문자 ' + dailyVisitors.toLocaleString() + '명으로 양호한 트래픽입니다.');
            } else if (dailyVisitors >= 100) {
                goodPoints.push('일일 방문자 ' + dailyVisitors.toLocaleString() + '명으로 기본 트래픽이 있습니다.');
            }

            // 활동량 관련
            if (recentPosts >= 30) {
                goodPoints.push('최근 30일간 ' + recentPosts + '개 포스팅으로 활동량이 매우 좋습니다!');
            } else if (recentPosts >= 20) {
                goodPoints.push('최근 30일간 ' + recentPosts + '개 포스팅으로 꾸준히 활동 중입니다.');
            } else if (recentPosts >= 12) {
                goodPoints.push('주 3회 이상 포스팅 패턴을 유지하고 있습니다.');
            }

            // 이웃 관련
            if (neighbors >= 1000) {
                goodPoints.push('이웃 ' + neighbors.toLocaleString() + '명으로 탄탄한 팬층을 보유하고 있습니다.');
            } else if (neighbors >= 500) {
                goodPoints.push('이웃 ' + neighbors.toLocaleString() + '명으로 적절한 네트워크가 형성되어 있습니다.');
            }

            // 이미지 관련
            if (avgImages >= 5 && avgImages <= 15) {
                goodPoints.push('평균 이미지 ' + avgImages + '장으로 적절한 이미지 활용을 하고 있습니다.');
            } else if (avgImages > 15) {
                goodPoints.push('이미지를 풍부하게 사용하고 있습니다(평균 ' + avgImages + '장).');
            }

            // 제목 관련
            if (avgTitleLength >= 20 && avgTitleLength <= 45) {
                goodPoints.push('제목 길이가 평균 ' + avgTitleLength + '자로 적절합니다.');
            }

            // 노출률 관련
            if (indexRate >= 70) {
                goodPoints.push('검색 노출률 ' + indexRate + '%로 우수합니다! 키워드 전략이 효과적입니다.');
            } else if (indexRate >= 50) {
                goodPoints.push('검색 노출률 ' + indexRate + '%로 양호합니다.');
            }

            // 참여도 관련
            if (avgEngagement >= 10) {
                goodPoints.push('평균 반응(공감+댓글) ' + avgEngagement + '개로 독자와의 소통이 활발합니다.');
            } else if (avgEngagement >= 5) {
                goodPoints.push('기본적인 독자 반응이 있습니다(평균 ' + avgEngagement + '개).');
            }

            // 나쁜점 (개선해야 할 점)
            let badPoints = [];

            // 등급 관련
            if (score < 45) {
                badPoints.push('현재 ' + grade + ' 등급으로 검색 노출에 불리합니다. 양질의 콘텐츠로 신뢰도를 높여야 합니다.');
            } else if (score < 60) {
                badPoints.push('현재 ' + grade + ' 등급입니다. 상위 노출을 위해 더 많은 노력이 필요합니다.');
            }

            // 방문자 관련
            if (dailyVisitors < 50) {
                badPoints.push('일일 방문자가 ' + dailyVisitors + '명으로 매우 적습니다. 검색 노출 최적화가 시급합니다.');
            } else if (dailyVisitors < 100) {
                badPoints.push('일일 방문자가 ' + dailyVisitors + '명으로 낮은 편입니다. 키워드 전략 점검이 필요합니다.');
            }

            // 활동량 관련
            if (recentPosts < 5) {
                badPoints.push('최근 30일간 포스팅이 ' + recentPosts + '개로 매우 적습니다. 최소 주 3회 이상 포스팅하세요!');
            } else if (recentPosts < 12) {
                badPoints.push('최근 30일간 포스팅이 ' + recentPosts + '개입니다. 주 3회(월 12회) 이상 권장합니다.');
            }

            // 이웃 관련
            if (neighbors < 100) {
                badPoints.push('이웃이 ' + neighbors + '명으로 적습니다. 적극적인 이웃 소통으로 네트워크를 넓히세요.');
            } else if (neighbors < 300) {
                badPoints.push('이웃이 ' + neighbors + '명입니다. 서로이웃을 더 늘려보세요.');
            }

            // 이미지 관련
            if (avgImages < 3) {
                badPoints.push('평균 이미지가 ' + avgImages + '장으로 부족합니다. 최소 5장 이상 권장합니다.');
            } else if (avgImages < 5) {
                badPoints.push('평균 이미지 ' + avgImages + '장은 조금 부족합니다. 5~10장을 목표로 하세요.');
            } else if (avgImages > 25) {
                badPoints.push('이미지가 너무 많습니다(평균 ' + avgImages + '장). 페이지 로딩 속도에 영향을 줄 수 있습니다.');
            }

            // 제목 관련
            if (avgTitleLength < 15) {
                badPoints.push('제목이 너무 짧습니다(평균 ' + avgTitleLength + '자). 20~40자로 구체적으로 작성하세요.');
            } else if (avgTitleLength > 50) {
                badPoints.push('제목이 너무 깁니다(평균 ' + avgTitleLength + '자). 검색 결과에서 잘릴 수 있습니다.');
            }

            // 노출률 관련
            if (indexRate < 30) {
                badPoints.push('검색 노출률 ' + indexRate + '%로 매우 낮습니다! 키워드 전략을 전면 재검토하세요.');
            } else if (indexRate < 50) {
                badPoints.push('검색 노출률 ' + indexRate + '%로 낮습니다. 롱테일 키워드 활용을 권장합니다.');
            }

            // 참여도 관련
            if (avgEngagement < 2) {
                badPoints.push('평균 반응이 ' + avgEngagement + '개로 매우 적습니다. 글 마지막에 공감/댓글 유도 문구를 넣으세요.');
            } else if (avgEngagement < 5) {
                badPoints.push('독자 반응이 부족합니다(평균 ' + avgEngagement + '개). 다른 블로그에 먼저 소통해보세요.');
            }

            // 기본 좋은점이 없으면 추가
            if (goodPoints.length === 0) {
                goodPoints.push('블로그를 운영하고 계신 것 자체가 좋은 시작입니다!');
                goodPoints.push('꾸준함이 가장 중요합니다. 포기하지 마세요!');
            }

            // HTML 생성
            let html = '';

            // 좋은점 (유지해야 할 점)
            html += '<div class="diagnosis-section">';
            html += '<div class="diagnosis-section-title diagnosis-good-title">✅ 좋은점 (유지해야 할 점)</div>';
            html += '<ul class="diagnosis-list diagnosis-good-list">';
            goodPoints.forEach(point => {
                html += '<li>' + point + '</li>';
            });
            html += '</ul>';
            html += '</div>';

            // 나쁜점 (개선해야 할 점)
            if (badPoints.length > 0) {
                html += '<div class="diagnosis-section">';
                html += '<div class="diagnosis-section-title diagnosis-bad-title">⚠️ 개선이 필요한 점</div>';
                html += '<ul class="diagnosis-list diagnosis-bad-list">';
                badPoints.forEach(point => {
                    html += '<li>' + point + '</li>';
                });
                html += '</ul>';
                html += '</div>';
            }

            // 다음 등급까지 필요한 것
            const nextGradeInfo = getNextGradeInfo(score, grade);
            if (nextGradeInfo) {
                html += '<div class="diagnosis-section next-grade-section">';
                html += '<div class="diagnosis-section-title" style="color: #f093fb;">🎯 다음 등급까지</div>';
                html += '<div class="next-grade-box">';
                html += '<div class="next-grade-progress">';
                html += '<span class="current-grade" style="color: ' + (idx.color || '#9E9E9E') + '">' + grade + '</span>';
                html += '<div class="progress-bar"><div class="progress-fill" style="width: ' + nextGradeInfo.progress + '%; background: linear-gradient(90deg, ' + (idx.color || '#9E9E9E') + ', ' + nextGradeInfo.nextColor + ');"></div></div>';
                html += '<span class="next-grade" style="color: ' + nextGradeInfo.nextColor + '">' + nextGradeInfo.nextGrade + '</span>';
                html += '</div>';
                html += '<div class="next-grade-need">';
                html += '<strong>' + nextGradeInfo.pointsNeeded + '점</strong> 더 필요 (현재 ' + score.toFixed(1) + '점 → 목표 ' + nextGradeInfo.targetScore + '점)';
                html += '</div>';
                html += '<ul class="next-grade-tips">';
                nextGradeInfo.tips.forEach(tip => {
                    html += '<li>' + tip + '</li>';
                });
                html += '</ul>';
                html += '</div>';
                html += '</div>';
            }

            return html;
        }

        // 다음 등급 정보 계산
        function getNextGradeInfo(score, currentGrade) {
            const grades = [
                { grade: '저품', min: 0, max: 30, color: '#F44336' },
                { grade: '일반', min: 30, max: 45, color: '#9E9E9E' },
                { grade: '준최7', min: 45, max: 50, color: '#FF8A65' },
                { grade: '준최6', min: 50, max: 55, color: '#FFAB91' },
                { grade: '준최5', min: 55, max: 60, color: '#FFE082' },
                { grade: '준최4', min: 60, max: 65, color: '#FFD54F' },
                { grade: '준최3', min: 65, max: 70, color: '#FFC107' },
                { grade: '준최2', min: 70, max: 75, color: '#B9F6CA' },
                { grade: '준최1', min: 75, max: 80, color: '#69F0AE' },
                { grade: 'NB', min: 80, max: 85, color: '#00E676' },
                { grade: '최적', min: 85, max: 100, color: '#00C853' }
            ];

            // 현재 등급 인덱스 찾기
            let currentIdx = grades.findIndex(g => g.grade === currentGrade);
            if (currentIdx === -1) currentIdx = 0;

            // 이미 최고 등급이면 null
            if (currentIdx >= grades.length - 1) {
                return null;
            }

            const nextGradeData = grades[currentIdx + 1];
            const targetScore = nextGradeData.min;
            const pointsNeeded = Math.max(0, targetScore - score).toFixed(1);
            const currentGradeData = grades[currentIdx];
            const progressInGrade = ((score - currentGradeData.min) / (currentGradeData.max - currentGradeData.min)) * 100;

            // 등급별 추천 팁
            let tips = [];
            if (score < 45) {
                tips = ['매일 1개 이상 포스팅하기', '이미지 5장 이상 사용하기', '이웃 소통 늘리기'];
            } else if (score < 60) {
                tips = ['검색 키워드를 제목에 포함', '본문 2000자 이상 작성', '공감/댓글 유도하기'];
            } else if (score < 75) {
                tips = ['롱테일 키워드 공략', 'ALT 태그 최적화', '체류시간 늘리는 콘텐츠'];
            } else {
                tips = ['틈새 키워드 발굴', '시리즈 콘텐츠 제작', '독자 충성도 높이기'];
            }

            return {
                nextGrade: nextGradeData.grade,
                nextColor: nextGradeData.color,
                targetScore: targetScore,
                pointsNeeded: pointsNeeded,
                progress: Math.min(100, progressInGrade),
                tips: tips
            };
        }

        function generateTitleAdvice(data) {
            const posts = data.posts_with_index || [];
            const avgTitleLength = posts.length > 0
                ? Math.round(posts.reduce((sum, p) => sum + (p.title?.length || 0), 0) / posts.length)
                : 0;

            let advice = `<ul>`;
            advice += `<li>키워드는 <span class="highlight">제목 앞쪽</span>에 배치하세요</li>`;
            advice += `<li>제목 길이는 <span class="highlight">30~40자</span>가 적당합니다</li>`;
            advice += `<li><span class="highlight">[키워드]</span> 형태로 핵심 키워드를 강조하세요</li>`;
            advice += `<li>숫자 사용: "5가지 방법", "TOP 10" 등이 클릭률 높음</li>`;
            advice += `</ul>`;

            if (avgTitleLength > 0) {
                if (avgTitleLength < 25) {
                    advice += `<div class="tip-box">💡 현재 평균 제목 길이가 ${avgTitleLength}자로 짧습니다. 조금 더 구체적으로 작성해보세요.</div>`;
                } else if (avgTitleLength > 50) {
                    advice += `<div class="tip-box">💡 현재 평균 제목 길이가 ${avgTitleLength}자로 깁니다. 핵심만 담아 간결하게 줄여보세요.</div>`;
                }
            }

            return advice;
        }

        function generateContentAdvice(data) {
            let advice = `<ul>`;
            advice += `<li>본문 글자 수: <span class="highlight">최소 1,500자 이상</span> 권장</li>`;
            advice += `<li>키워드 밀도: 본문에 키워드 <span class="highlight">5~10회</span> 자연스럽게 포함</li>`;
            advice += `<li>소제목(H2, H3) 활용하여 <span class="highlight">가독성</span> 높이기</li>`;
            advice += `<li>첫 문단에 <span class="highlight">핵심 키워드</span> 포함 필수</li>`;
            advice += `<li>마지막에 <span class="highlight">요약 정리</span>로 마무리</li>`;
            advice += `</ul>`;
            advice += `<div class="tip-box">💡 네이버는 체류시간을 중요하게 봅니다. 읽을 거리가 풍부해야 합니다!</div>`;

            return advice;
        }

        function generateImageAdvice(data) {
            const posts = data.posts_with_index || [];
            const avgImages = posts.length > 0
                ? Math.round(posts.reduce((sum, p) => sum + (p.images || 0), 0) / posts.length)
                : 0;

            let advice = `<ul>`;
            advice += `<li>이미지 개수: <span class="highlight">5~15장</span>이 적당</li>`;
            advice += `<li>첫 이미지는 <span class="highlight">대표 이미지</span>로 신경쓰기</li>`;
            advice += `<li>이미지 파일명에 <span class="highlight">키워드</span> 포함</li>`;
            advice += `<li>ALT 태그(대체 텍스트)에 <span class="highlight">설명</span> 작성</li>`;
            advice += `<li>저작권 없는 이미지 or <span class="highlight">직접 촬영</span> 권장</li>`;
            advice += `</ul>`;

            if (avgImages < 3) {
                advice += `<div class="tip-box">⚠️ 평균 이미지가 ${avgImages}장으로 적습니다. 최소 5장 이상 권장!</div>`;
            } else if (avgImages > 20) {
                advice += `<div class="tip-box">💡 평균 이미지가 ${avgImages}장입니다. 너무 많으면 로딩이 느려질 수 있어요.</div>`;
            } else {
                advice += `<div class="tip-box">✅ 평균 이미지 ${avgImages}장으로 적절합니다!</div>`;
            }

            return advice;
        }

        function generateTimingAdvice(data) {
            let advice = `<ul>`;
            advice += `<li><span class="highlight">오전 7~9시</span>: 출근 시간대, 모바일 검색 많음</li>`;
            advice += `<li><span class="highlight">점심 12~13시</span>: 점심시간 검색 트래픽 높음</li>`;
            advice += `<li><span class="highlight">저녁 20~22시</span>: 퇴근 후 여유 시간대</li>`;
            advice += `<li>요일: <span class="highlight">화~목요일</span>이 가장 효과적</li>`;
            advice += `<li>주말보다 <span class="highlight">평일</span>이 검색량 많음</li>`;
            advice += `</ul>`;
            advice += `<div class="tip-box">💡 꾸준함이 중요! 매일 같은 시간에 발행하면 네이버가 신뢰합니다.</div>`;

            return advice;
        }

        function generateExposureAdvice(data) {
            const posts = data.posts_with_index || [];
            const indexed = posts.filter(p => p.exposure === 'indexed').length;
            const missing = posts.filter(p => p.exposure === 'missing').length;
            const rate = posts.length > 0 ? Math.round((indexed / posts.length) * 100) : 0;

            let advice = `<ul>`;
            advice += `<li>키워드 <span class="highlight">검색량 확인</span> 후 작성 (네이버 키워드 도구)</li>`;
            advice += `<li><span class="highlight">롱테일 키워드</span>로 경쟁 피하기 (예: "서울 맛집" → "강남역 점심 맛집 추천")</li>`;
            advice += `<li>제목, 본문, 태그에 <span class="highlight">일관된 키워드</span> 사용</li>`;
            advice += `<li>발행 후 <span class="highlight">24시간 내</span> 노출 확인</li>`;
            advice += `</ul>`;

            if (posts.length > 0) {
                if (rate >= 70) {
                    advice += `<div class="tip-box">✅ 노출률 ${rate}% (${indexed}/${posts.length}개) - 좋습니다!</div>`;
                } else if (rate >= 40) {
                    advice += `<div class="tip-box">⚠️ 노출률 ${rate}% (${indexed}/${posts.length}개) - 키워드 선정을 재검토하세요.</div>`;
                } else {
                    advice += `<div class="tip-box">🚨 노출률 ${rate}% (${indexed}/${posts.length}개) - 키워드 전략 수정이 필요합니다!</div>`;
                }
            }

            return advice;
        }

        function generateActivityAdvice(data) {
            const recentPosts = data.recent_30days_posts || 0;
            const neighbors = data.neighbors || 0;

            let advice = `<ul>`;
            advice += `<li>포스팅: <span class="highlight">주 3~5회</span> 꾸준히 발행</li>`;
            advice += `<li>이웃 관리: <span class="highlight">서로이웃</span> 적극 활용</li>`;
            advice += `<li>댓글/공감: 다른 블로그에 <span class="highlight">먼저 소통</span>하기</li>`;
            advice += `<li>시리즈 포스팅으로 <span class="highlight">재방문</span> 유도</li>`;
            advice += `<li>양보다 <span class="highlight">질</span>! 복붙/어뷰징 절대 금지</li>`;
            advice += `</ul>`;

            if (recentPosts < 12) {
                advice += `<div class="tip-box">⚠️ 월 ${recentPosts}회 포스팅 중. 최소 12회(주 3회) 이상 목표!</div>`;
            }

            if (neighbors < 100) {
                advice += `<div class="tip-box">💡 이웃 ${neighbors}명. 같은 주제 블로거와 서로이웃 늘려보세요!</div>`;
            }

            return advice;
        }

        function displayResult(data) {
            const resultDiv = document.getElementById('result');
            const idx = data.index || {};

            // 전역 데이터 저장 (PDF, 비교 기능용)
            currentAnalysisData = data;
            saveFullHistory(data);

            // 주간 평균 계산
            const weeklyAvg = getWeeklyAverage(data.blog_id);

            // SEO 점수 계산
            const posts = data.posts_with_index || [];
            let seoScore = { total: 0, title: 0, image: 0, content: 0, exposure: 0 };
            if (posts.length > 0) {
                // 제목 점수
                let titleScores = posts.slice(0, 10).map(p => {
                    let s = 0;
                    const len = (p.title || '').length;
                    if (len >= 20 && len <= 45) s += 10;
                    else if (len >= 15 && len <= 50) s += 5;
                    if (p.keyword && (p.title || '').includes(p.keyword)) s += 15;
                    return s;
                });
                seoScore.title = Math.round(titleScores.reduce((a, b) => a + b, 0) / titleScores.length);

                // 이미지 점수
                let imageScores = posts.slice(0, 10).map(p => {
                    let s = 0;
                    const img = p.images || 0;
                    if (img >= 5 && img <= 15) s += 15;
                    else if (img >= 3) s += 10;
                    else if (img > 0) s += 5;
                    if (p.image_seo?.alt_quality === 'excellent') s += 10;
                    else if (p.image_seo?.alt_quality === 'good') s += 7;
                    else if (p.image_seo?.alt_quality === 'average') s += 4;
                    return s;
                });
                seoScore.image = Math.round(imageScores.reduce((a, b) => a + b, 0) / imageScores.length);

                // 콘텐츠 점수
                let contentScores = posts.slice(0, 10).map(p => {
                    let s = 0;
                    const chars = p.char_count || 0;
                    if (chars >= 2000) s += 15;
                    else if (chars >= 1500) s += 10;
                    else if (chars >= 1000) s += 5;
                    if ((p.subheading_count || 0) >= 2) s += 10;
                    else if ((p.subheading_count || 0) > 0) s += 5;
                    return s;
                });
                seoScore.content = Math.round(contentScores.reduce((a, b) => a + b, 0) / contentScores.length);

                // 노출 점수
                const indexed = posts.slice(0, 10).filter(p => p.exposure === 'indexed').length;
                seoScore.exposure = Math.round((indexed / Math.min(10, posts.length)) * 25);

                seoScore.total = seoScore.title + seoScore.image + seoScore.content + seoScore.exposure;
            }

            const seoGrade = seoScore.total >= 70 ? '우수' : seoScore.total >= 50 ? '양호' : seoScore.total >= 30 ? '보통' : '개선필요';
            const seoColor = seoScore.total >= 70 ? '#00C853' : seoScore.total >= 50 ? '#667eea' : seoScore.total >= 30 ? '#FFC107' : '#F44336';

            // 프로필 이미지 또는 기본 아이콘
            const blogInitial = (data.blog_nickname || data.blog_id || 'N').charAt(0).toUpperCase();
            const hasProfileImage = data.profile_image && data.profile_image.length > 10;

            resultDiv.innerHTML = `
                <div class="result">
                    <!-- SEO 점수 카드 -->
                    <div class="seo-score-card">
                        <div class="seo-score-header">
                            <span class="seo-score-title">🎯 SEO 점수 분석</span>
                            <span class="seo-total-score" style="color: ${seoColor}">${seoScore.total}/100 (${seoGrade})</span>
                        </div>
                        <div class="seo-breakdown">
                            <div class="seo-item">
                                <div class="seo-item-label">제목 SEO</div>
                                <div class="seo-item-value">${seoScore.title}/25</div>
                            </div>
                            <div class="seo-item">
                                <div class="seo-item-label">이미지 SEO</div>
                                <div class="seo-item-value">${seoScore.image}/25</div>
                            </div>
                            <div class="seo-item">
                                <div class="seo-item-label">콘텐츠 SEO</div>
                                <div class="seo-item-value">${seoScore.content}/25</div>
                            </div>
                            <div class="seo-item">
                                <div class="seo-item-label">노출 SEO</div>
                                <div class="seo-item-value">${seoScore.exposure}/25</div>
                            </div>
                        </div>
                        ${seoScore.total < 70 ? `
                        <div class="seo-recommendations">
                            ${seoScore.title < 15 ? '<div class="seo-rec-item">💡 제목에 키워드를 포함하고 20-45자로 작성하세요</div>' : ''}
                            ${seoScore.image < 15 ? '<div class="seo-rec-item">💡 이미지 5-15개 사용 및 ALT 태그 설정을 권장합니다</div>' : ''}
                            ${seoScore.content < 15 ? '<div class="seo-rec-item">💡 본문 2000자 이상, 소제목 2개 이상 사용을 권장합니다</div>' : ''}
                            ${seoScore.exposure < 15 ? '<div class="seo-rec-item">💡 롱테일 키워드로 검색 노출률을 높이세요</div>' : ''}
                        </div>
                        ` : ''}
                    </div>

                    <!-- 프로필 카드 -->
                    <div class="profile-card">
                        <div class="profile-image" style="
                            ${hasProfileImage ? `background-image: url('${data.profile_image}');` : ''}
                            background: ${hasProfileImage ? '' : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'};
                            border-color: ${idx.color || '#667eea'};
                            box-shadow: 0 0 25px ${idx.color}40;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            font-size: 36px;
                            font-weight: 700;
                            color: white;
                            text-shadow: 0 2px 4px #0000004d;
                        ">${hasProfileImage ? '' : blogInitial}</div>

                        <div class="profile-info">
                            <h2>${data.blog_name || data.blog_nickname || data.blog_id}</h2>
                            <a href="${getBlogUrl(data)}" target="_blank" class="blog-link">
                                <p class="blog-id">${getBlogDisplayUrl(data)} 🔗</p>
                            </a>
                            <div class="profile-meta">
                                <span>📅 블로그 ${Math.floor(data.blog_age_days / 365) || '?'}년차</span>
                                <span>📝 총 ${(data.total_posts || 0).toLocaleString()}개 포스팅</span>
                            </div>
                        </div>
                        
                        <div class="index-badge" style="border: 2px solid ${idx.color}50;">
                            <div class="index-label">블로그 지수</div>
                            <div class="index-grade" style="color: ${idx.color}; text-shadow: 0 0 20px ${idx.color}80;">
                                ${idx.grade || '분석중'}
                            </div>
                            <div class="index-score">${idx.score || 0} / 100점</div>
                        </div>
                    </div>
                    
                    <!-- 통계 그리드 -->
                    <div class="stats-grid" style="grid-template-columns: repeat(5, 1fr);">
                        <div class="stat-card">
                            <div class="stat-icon" style="background: #667eea33;">👁️</div>
                            <div class="stat-value">${(data.daily_visitors || 0).toLocaleString()}</div>
                            <div class="stat-label">일일 방문자</div>
                            ${weeklyAvg && weeklyAvg.count >= 3 ? `
                            <div class="stat-sublabel" style="font-size: 10px; color: #ffffff80; margin-top: 4px;">
                                📊 ${weeklyAvg.count}일 평균: ${weeklyAvg.average.toLocaleString()}명
                            </div>` : weeklyAvg && weeklyAvg.count >= 1 ? `
                            <div class="stat-sublabel" style="font-size: 10px; color: #ff9800b3; margin-top: 4px;">
                                ⚠️ ${3 - weeklyAvg.count}일 더 분석 필요
                            </div>` : ''}
                        </div>
                        <div class="stat-card">
                            <div class="stat-icon" style="background: #00e67633;">📊</div>
                            <div class="stat-value">${(data.total_visitors || 0).toLocaleString()}</div>
                            <div class="stat-label">전체 방문자</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-icon" style="background: #f093fb33;">👥</div>
                            <div class="stat-value">${(data.neighbors || 0).toLocaleString()}</div>
                            <div class="stat-label">이웃 수</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-icon" style="background: #ffc10733;">📝</div>
                            <div class="stat-value">${(data.total_posts || 0).toLocaleString()}</div>
                            <div class="stat-label">총 포스팅</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-icon" style="background: #ff572233;">🔥</div>
                            <div class="stat-value">${data.recent_30days_posts || 0}</div>
                            <div class="stat-label">최근 30일</div>
                        </div>
                    </div>
                    
                    <!-- 지수 상세 -->
                    <div class="section-card">
                        <h3 class="section-title">🏆 지수 등급 현황</h3>

                        ${idx.data_reliability === 'low' ? `
                        <div style="background: #ff980033; border: 1px solid #ff980080; border-radius: 8px; padding: 10px 14px; margin-bottom: 15px; display: flex; align-items: center; gap: 10px;">
                            <span style="font-size: 18px;">⚠️</span>
                            <div>
                                <div style="font-size: 13px; font-weight: 600; color: #FFB74D;">분석 데이터 부족</div>
                                <div style="font-size: 11px; color: #ffffff99;">정확한 분석을 위해 3일 이상 분석해주세요. 현재는 추정값입니다.</div>
                            </div>
                        </div>
                        ` : idx.data_reliability === 'medium' ? `
                        <div style="background: #667eea26; border: 1px solid #667eea4d; border-radius: 8px; padding: 8px 12px; margin-bottom: 15px; font-size: 11px; color: #ffffffb3;">
                            📊 ${idx.reliability_msg}
                        </div>
                        ` : idx.data_reliability === 'high' ? `
                        <div style="background: #00c85326; border: 1px solid #00c8534d; border-radius: 8px; padding: 8px 12px; margin-bottom: 15px; font-size: 11px; color: #ffffffb3;">
                            ✅ ${idx.reliability_msg}
                        </div>
                        ` : ''}

                        <div class="progress-bar">
                            <div class="progress-fill" style="
                                width: ${Math.min(100, idx.score || 0)}%;
                                background: linear-gradient(90deg, ${idx.color}, ${idx.color}aa);
                                box-shadow: 0 0 15px ${idx.color}60;
                            "></div>
                        </div>
                        
                        <div class="grade-labels">
                            <span>저품</span>
                            <span>일반</span>
                            <span>준최7</span>
                            <span>준최4</span>
                            <span>준최1</span>
                            <span>NB</span>
                            <span>최적</span>
                        </div>

                        <div class="breakdown-grid" style="grid-template-columns: repeat(4, 1fr);">
                            <div class="breakdown-item" style="background: #667eea26; border: 1px solid #667eea4d;">
                                <div class="breakdown-label">노출 지수</div>
                                <div class="breakdown-value" style="color: #667eea;">${idx.breakdown?.exposure || 0}</div>
                                <div class="breakdown-max">/ 100점 (70%)</div>
                            </div>
                            <div class="breakdown-item">
                                <div class="breakdown-label">활동 지수</div>
                                <div class="breakdown-value">${idx.breakdown?.activity || 0}</div>
                                <div class="breakdown-max">/ 100점 (15%)</div>
                            </div>
                            <div class="breakdown-item">
                                <div class="breakdown-label">신뢰 지수</div>
                                <div class="breakdown-value">${idx.breakdown?.trust || 0}</div>
                                <div class="breakdown-max">/ 100점 (15%)</div>
                            </div>
                            <div class="breakdown-item" style="background: linear-gradient(135deg, #667eea33, #764ba233); border: 1px solid ${idx.color}50;">
                                <div class="breakdown-label">종합</div>
                                <div class="breakdown-value" style="color: ${idx.color}; font-size: 22px;">${idx.score || 0}</div>
                                <div class="breakdown-max">/ 100점</div>
                            </div>
                        </div>
                    </div>

                    <!-- 차트 섹션 -->
                    <div class="charts-grid">
                        <!-- 지수 구성 도넛 차트 -->
                        <div class="chart-card">
                            <div class="chart-title">📊 지수 구성 비율</div>
                            <div class="chart-container">
                                <canvas id="indexDonutChart"></canvas>
                            </div>
                        </div>

                        <!-- 노출 현황 파이 차트 -->
                        ${(data.posts_with_index && data.posts_with_index.length > 0) ? `
                        <div class="chart-card">
                            <div class="chart-title">🔍 키워드 노출 현황</div>
                            <div class="chart-container">
                                <canvas id="exposureChart"></canvas>
                            </div>
                        </div>
                        ` : ''}

                        <!-- 포스팅 통계 바 차트 -->
                        ${(data.posts_with_index && data.posts_with_index.length > 0) ? `
                        <div class="chart-card" style="grid-column: span 2;">
                            <div class="chart-title">💬 최근 포스팅 반응 (공감/댓글)</div>
                            <div class="chart-container-large">
                                <canvas id="engagementChart"></canvas>
                            </div>
                        </div>
                        ` : ''}
                    </div>

                    <!-- 블로그 코칭 섹션 -->
                    <div class="coaching-section">
                        <div class="coaching-header">
                            <span class="coaching-icon">🎓</span>
                            <div>
                                <div class="coaching-title">블로그 성장 분석</div>
                                <div class="coaching-subtitle">현재 상태 분석 및 맞춤형 조언 (클릭하여 펼치기)</div>
                            </div>
                        </div>

                        <!-- 현재 상태 진단 (항상 펼쳐져 있음) -->
                        <div class="diagnosis-box">
                            <div class="diagnosis-title">📋 현재 상태 진단</div>
                            <div class="diagnosis-content">
                                ${generateDiagnosis(data)}
                            </div>
                        </div>

                        <!-- 맞춤형 조언 아코디언 -->
                        <div class="accordion-wrapper">
                            <!-- 제목 작성법 -->
                            <div class="accordion-item">
                                <div class="accordion-header" onclick="toggleAccordion(this)">
                                    <div class="accordion-header-content">
                                        <span class="accordion-icon">📝</span>
                                        <span class="accordion-title">제목 작성법</span>
                                    </div>
                                    <span class="accordion-arrow">▼</span>
                                </div>
                                <div class="accordion-body">
                                    <div class="accordion-content">
                                        ${generateTitleAdvice(data)}
                                    </div>
                                </div>
                            </div>

                            <!-- 본문 작성법 -->
                            <div class="accordion-item">
                                <div class="accordion-header" onclick="toggleAccordion(this)">
                                    <div class="accordion-header-content">
                                        <span class="accordion-icon">📄</span>
                                        <span class="accordion-title">본문 작성법</span>
                                    </div>
                                    <span class="accordion-arrow">▼</span>
                                </div>
                                <div class="accordion-body">
                                    <div class="accordion-content">
                                        ${generateContentAdvice(data)}
                                    </div>
                                </div>
                            </div>

                            <!-- 이미지 최적화 -->
                            <div class="accordion-item">
                                <div class="accordion-header" onclick="toggleAccordion(this)">
                                    <div class="accordion-header-content">
                                        <span class="accordion-icon">🖼</span>
                                        <span class="accordion-title">이미지 최적화</span>
                                    </div>
                                    <span class="accordion-arrow">▼</span>
                                </div>
                                <div class="accordion-body">
                                    <div class="accordion-content">
                                        ${generateImageAdvice(data)}
                                    </div>
                                </div>
                            </div>

                            <!-- 배포 시간 -->
                            <div class="accordion-item">
                                <div class="accordion-header" onclick="toggleAccordion(this)">
                                    <div class="accordion-header-content">
                                        <span class="accordion-icon">⏰</span>
                                        <span class="accordion-title">최적 배포 시간</span>
                                    </div>
                                    <span class="accordion-arrow">▼</span>
                                </div>
                                <div class="accordion-body">
                                    <div class="accordion-content">
                                        ${generateTimingAdvice(data)}
                                    </div>
                                </div>
                            </div>

                            <!-- 노출 개선 -->
                            <div class="accordion-item">
                                <div class="accordion-header" onclick="toggleAccordion(this)">
                                    <div class="accordion-header-content">
                                        <span class="accordion-icon">🔍</span>
                                        <span class="accordion-title">검색 노출 개선</span>
                                    </div>
                                    <span class="accordion-arrow">▼</span>
                                </div>
                                <div class="accordion-body">
                                    <div class="accordion-content">
                                        ${generateExposureAdvice(data)}
                                    </div>
                                </div>
                            </div>

                            <!-- 활동 개선 -->
                            <div class="accordion-item">
                                <div class="accordion-header" onclick="toggleAccordion(this)">
                                    <div class="accordion-header-content">
                                        <span class="accordion-icon">💪</span>
                                        <span class="accordion-title">활동 지수 높이기</span>
                                    </div>
                                    <span class="accordion-arrow">▼</span>
                                </div>
                                <div class="accordion-body">
                                    <div class="accordion-content">
                                        ${generateActivityAdvice(data)}
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- 결과 중간 광고 (300x250) -->
                    <div class="ad-content-wrapper ad-between-sections">
                        <div class="ad-content-container">
                            <div class="ad-label">광고</div>
                            <ins class="kakao_ad_area" style="display:none;"
                            data-ad-unit = "DAN-qYU1Nbac9rUaGFpF"
                            data-ad-width = "300"
                            data-ad-height = "250"></ins>
                        </div>
                    </div>

                    <!-- 게시글 진단 섹션 -->
                    ${(data.posts_with_index && data.posts_with_index.length > 0) ? `
                    <div class="section-card">
                        <h3 class="section-title">📋 게시글 진단 (최근 ${data.posts_with_index.length}개) <span style="font-size: 12px; color: #ffffff66; font-weight: normal;">ⓘ 포스팅별 상태 및 최적화 점수</span></h3>
                        <div style="font-size: 11px; color: #ffffff80; margin-bottom: 12px; padding: 8px; background: #ffffff0d; border-radius: 6px;">
                            💡 <strong>진단 결과:</strong> 누락 상태인 글은 네이버 검색에서 제외된 상태입니다. 최적화 점수 70점 이상을 목표로 하세요.
                        </div>
                        <div class="table-scroll-container">
                            <table class="post-diagnosis-table">
                                <thead>
                                    <tr>
                                        <th style="width: 25%;">제목</th>
                                        <th style="width: 8%;">누락</th>
                                        <th style="width: 18%;">형태소</th>
                                        <th style="width: 5%;">댓글</th>
                                        <th style="width: 5%;">공감</th>
                                        <th style="width: 5%;">사진</th>
                                        <th style="width: 12%;">최적화</th>
                                        <th style="width: 10%;">발행일</th>
                                        <th style="width: 12%;">분석</th>
                                    </tr>
                                </thead>
                                <tbody id="postsTableBody">
                                    ${data.posts_with_index.map(function(post, idx) {
                                        const score = calculatePostScore(post);
                                        const scoreColor = score >= 80 ? '#00C853' : score >= 60 ? '#667eea' : score >= 40 ? '#FFC107' : '#F44336';
                                        const scoreLabel = score >= 80 ? '우수' : score >= 60 ? '양호' : score >= 40 ? '보통' : '개선';

                                        // 누락여부 상태
                                        const missingStatus = post.exposure === 'indexed' ? '<span style="color: #00C853; font-weight: 600;">정상</span>' :
                                                             post.exposure === 'missing' ? '<span style="color: #F44336; font-weight: 600;">누락</span>' :
                                                             '<span style="color: #FFC107; font-weight: 600;">확인중</span>';

                                        // 형태소 키워드 (클릭 시 팝업)
                                        const allKeywords = getPostKeywords(post, 10);
                                        let keywordsHtml = '-';
                                        if (allKeywords.length > 0) {
                                            const firstKw = escapeHtmlAttr(allKeywords[0]);
                                            const remainCount = allKeywords.length - 1;
                                            const safeTitle = escapeHtmlAttr(post.title || '');
                                            const safeKeywords = allKeywords.map(escapeHtmlAttr).join('|||');
                                            if (remainCount > 0) {
                                                keywordsHtml = '<span class="morpheme-preview" data-keywords="' + safeKeywords + '" data-title="' + safeTitle + '" onclick="handleMorphemeClick(this)" style="cursor:pointer;background:#667eea33;padding:3px 8px;border-radius:4px;font-size:11px"><span style="color:#fff">' + firstKw + '</span> <span style="color:#667eea;font-size:10px">외 ' + remainCount + '개</span></span>';
                                            } else {
                                                keywordsHtml = '<span style="background:#667eea33;padding:3px 8px;border-radius:4px;font-size:11px">' + firstKw + '</span>';
                                            }
                                        }

                                        // 발행일 포맷
                                        const dateDisplay = formatRelativeDate(post.date);

                                        // 더보기 숨김 처리
                                        const hiddenClass = idx >= 5 ? 'hidden-post-row' : '';

                                        // 제목 이스케이핑
                                        const escapedTitle = (post.title || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

                                        return '<tr class="' + hiddenClass + '">' +
                                            '<td><a href="' + (post.link || '#') + '" target="_blank" class="post-title-link" title="' + escapedTitle + '">' + escapedTitle + '</a></td>' +
                                            '<td style="text-align: center;">' + missingStatus + '</td>' +
                                            '<td style="text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 120px;">' + keywordsHtml + '</td>' +
                                            '<td style="text-align: center;">' + (post.comments || 0) + '</td>' +
                                            '<td style="text-align: center;">' + (post.likes || 0) + '</td>' +
                                            '<td style="text-align: center;">' + (post.images || 0) + '</td>' +
                                            '<td style="text-align: center;"><span style="background: ' + scoreColor + '20; color: ' + scoreColor + '; padding: 3px 8px; border-radius: 10px; font-weight: 600; font-size: 11px;">' + score + '점</span></td>' +
                                            '<td style="text-align:center;color:#ffffff99;font-size:11px">' + dateDisplay + '</td>' +
                                            '<td><button class="analyze-btn" data-post-idx="' + idx + '" onclick="handlePostAnalysis(this)">🔍 상세</button></td>' +
                                        '</tr>';
                                    }).join('')}
                                </tbody>
                            </table>
                        </div>
                        ${data.posts_with_index.length > 5 ? `
                        <div class="load-more-container" id="loadMoreContainer">
                            <button class="load-more-btn" onclick="toggleMorePosts()">
                                <span id="loadMoreText">+ 더보기 (${data.posts_with_index.length - 5}개)</span>
                            </button>
                        </div>
                        ` : ''}
                    </div>

                    <!-- 형태소 분석 섹션 -->
                    <div class="section-card">
                        <h3 class="section-title">📝 형태소 분석 <span style="font-size: 12px; color: #ffffff66; font-weight: normal;">ⓘ 제목에서 자주 사용하는 키워드</span></h3>
                        <div style="display: flex; gap: 20px; flex-wrap: wrap;">
                            <div style="flex: 1; min-width: 200px;">
                                <table style="width: 100%; border-collapse: collapse;">
                                    <thead>
                                        <tr style="border-bottom: 1px solid #ffffff1a;">
                                            <th style="text-align: left; padding: 8px; color: #ffffffb3;">형태소</th>
                                            <th style="text-align: center; padding: 8px; color: #ffffffb3;">빈도수</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        ${getMorphemeAnalysis(data.posts_with_index).slice(0, 10).map(function(item) {
                                            return '<tr style="border-bottom: 1px solid #ffffff0d;"><td style="padding: 8px;">' + item.word + '</td><td style="text-align: center; padding: 8px; color: #667eea; font-weight: 600;">' + item.count + '</td></tr>';
                                        }).join('')}
                                    </tbody>
                                </table>
                            </div>
                            <div style="flex: 1; min-width: 200px;">
                                <div style="padding: 12px; background: #667eea1a; border-radius: 8px; margin-bottom: 12px;">
                                    <div style="font-size: 11px; color: #ffffff80; margin-bottom: 4px;">🏷️ 주요 태그</div>
                                    <div style="display: flex; flex-wrap: wrap; gap: 6px;">
                                        ${getMorphemeAnalysis(data.posts_with_index).slice(0, 6).map(function(item) {
                                            return '<span style="background: #667eea4d; padding: 4px 10px; border-radius: 12px; font-size: 12px;">' + item.word + '</span>';
                                        }).join('')}
                                    </div>
                                </div>
                                <div style="font-size: 11px; color: #ffffff80; padding: 8px;">
                                    💡 <strong>팁:</strong> 자주 사용하는 키워드가 블로그 주제와 일치하면 검색 노출에 유리합니다.
                                </div>
                            </div>
                        </div>
                    </div>

                    ` : ''}

                    <div class="info-box">
                        ℹ️ <strong>참고:</strong> 방문자 수는 블로그 위젯이 공개 설정되어 있어야 정확하게 표시됩니다.
                        지수는 공개된 데이터를 기반으로 자체 알고리즘으로 계산한 값입니다.
                    </div>

                    <!-- 결과 하단 광고 (250x250) -->
                    <div class="ad-content-wrapper hide-mobile ad-between-sections">
                        <div class="ad-content-container">
                            <div class="ad-label">광고</div>
                            <ins class="kakao_ad_area" style="display:none;"
                            data-ad-unit = "DAN-swwvk4Kp8cMpG1FI"
                            data-ad-width = "250"
                            data-ad-height = "250"></ins>
                        </div>
                    </div>

                    <!-- PDF 다운로드 버튼 -->
                    <div style="text-align: center; margin-top: 32px; padding-top: 24px; border-top: 1px solid #ffffff1a;">
                        <button class="pdf-download-btn" onclick="downloadPDF()" style="margin: 0 auto;">
                            📄 PDF 리포트 다운로드
                        </button>
                        <p style="margin-top: 12px; font-size: 11px; color: #ffffff66;">분석 결과를 PDF 파일로 저장합니다</p>
                    </div>
                </div>

                <!-- 포스팅 상세 분석 모달 -->
                <div id="analysisModal" class="modal-overlay" onclick="closeModalOnOverlay(event)">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h3>🔍 포스팅 상세 분석</h3>
                            <button class="modal-close" onclick="closeAnalysisModal()">&times;</button>
                        </div>
                        <div class="modal-body" id="analysisModalBody">
                            <!-- 분석 내용이 동적으로 들어감 -->
                        </div>
                    </div>
                </div>
            `;

            // 차트 렌더링
            setTimeout(() => renderCharts(data), 100);

            // 카카오 애드핏 광고 재렌더링 (동적 콘텐츠용)
            setTimeout(() => {
                if (typeof kakaoAdFit !== 'undefined' && kakaoAdFit.render) {
                    kakaoAdFit.render();
                } else if (typeof adfit !== 'undefined' && adfit.render) {
                    adfit.render();
                }
            }, 200);
        }

        // 형태소 클릭 핸들러
        function handleMorphemeClick(element) {
            // HTML 엔티티 디코딩
            function decodeHtml(str) {
                const txt = document.createElement('textarea');
                txt.innerHTML = str;
                return txt.value;
            }
            const rawKeywords = element.getAttribute('data-keywords') || '';
            const keywords = rawKeywords.split('|||').map(decodeHtml);
            const title = decodeHtml(element.getAttribute('data-title') || '');
            showMorphemePopup(keywords, title);
        }

        // 포스트 분석 클릭 핸들러
        function handlePostAnalysis(element) {
            const idx = parseInt(element.getAttribute('data-post-idx'));
            if (currentAnalysisData && currentAnalysisData.posts_with_index && currentAnalysisData.posts_with_index[idx]) {
                showPostAnalysis(currentAnalysisData.posts_with_index[idx]);
            }
        }

        // 형태소 팝업 함수
        function showMorphemePopup(keywords, title) {
            // 기존 팝업이 있으면 제거
            const existingPopup = document.querySelector('.morpheme-popup-overlay');
            if (existingPopup) existingPopup.remove();

            const overlay = document.createElement('div');
            overlay.className = 'morpheme-popup-overlay';
            overlay.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: #000000b3; z-index: 10000; display: flex; align-items: center; justify-content: center; padding: 20px;';
            overlay.onclick = function(e) { if (e.target === overlay) overlay.remove(); };

            const popup = document.createElement('div');
            popup.style.cssText = 'background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); border-radius: 16px; padding: 24px; max-width: 400px; width: 100%; border: 1px solid #ffffff1a; box-shadow: 0 20px 60px #00000080;';

            const keywordTags = keywords.map(function(kw) {
                const naverSearchUrl = 'https://search.naver.com/search.naver?query=' + encodeURIComponent(kw);
                return '<a href="' + naverSearchUrl + '" target="_blank" class="morpheme-keyword-link">' + kw + ' <span style="font-size:10px;opacity:0.7">🔍</span></a>';
            }).join('');

            popup.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                    <h3 style="color: #fff; font-size: 16px; margin: 0;">📝 형태소 분석</h3>
                    <button onclick="this.closest('.morpheme-popup-overlay').remove()" style="background: none; border: none; color: #ffffff80; font-size: 24px; cursor: pointer; padding: 0; line-height: 1;">&times;</button>
                </div>
                <div style="background: #ffffff0d; border-radius: 8px; padding: 12px; margin-bottom: 16px;">
                    <div style="color: #ffffff80; font-size: 11px; margin-bottom: 4px;">제목</div>
                    <div style="color: #fff; font-size: 13px; line-height: 1.4;">${title}</div>
                </div>
                <div style="color: #ffffff80; font-size: 12px; margin-bottom: 8px;">추출된 키워드 (${keywords.length}개) <span style="color: #667eea;">· 클릭 시 네이버 검색</span></div>
                <div style="display: flex; flex-wrap: wrap; gap: 4px;">
                    ${keywordTags}
                </div>
            `;

            overlay.appendChild(popup);
            document.body.appendChild(overlay);
        }

        // 포스팅 상세 분석 모달 함수
        function showPostAnalysis(post) {
            const modal = document.getElementById('analysisModal');
            const body = document.getElementById('analysisModalBody');

            // 제목 분석
            const titleLength = (post.title || '').length;
            const titleAnalysis = analyzeTitleQuality(post.title, post.keyword);

            // 이미지 분석
            const imageAnalysis = analyzeImageCount(post.images || 0);

            // 본문 분석
            const contentAnalysis = analyzeContent(post.char_count || 0, post.subheading_count || 0, post.link_count || 0, post.has_video || false);

            // 노출 분석
            const exposureAnalysis = analyzeExposure(post.exposure, post.keyword);

            // 참여도 분석
            const engagementAnalysis = analyzeEngagement(post.likes || 0, post.comments || 0);

            // 종합 점수 계산
            const totalScore = calculatePostScore(post);
            const scoreClass = totalScore >= 80 ? 'score-excellent' : totalScore >= 60 ? 'score-good' : totalScore >= 40 ? 'score-average' : 'score-poor';
            const scoreLabel = totalScore >= 80 ? '우수' : totalScore >= 60 ? '양호' : totalScore >= 40 ? '보통' : '개선필요';

            body.innerHTML = `
                <div class="analysis-section">
                    <h4>📝 포스팅 정보</h4>
                    <div class="analysis-item">
                        <div class="analysis-label">제목</div>
                        <div class="analysis-value">${post.title || '제목 없음'}</div>
                    </div>
                    <div class="analysis-item">
                        <div class="analysis-label">작성일</div>
                        <div class="analysis-value">${post.date || '-'}</div>
                    </div>
                    <div class="analysis-item">
                        <div class="analysis-label">종합 점수</div>
                        <div class="analysis-value">
                            <span class="score-badge ${scoreClass}">${scoreLabel} ${totalScore}점</span>
                        </div>
                    </div>
                </div>

                <div class="analysis-section">
                    <h4>🏷️ 제목 분석</h4>
                    <div class="analysis-item">
                        <div class="analysis-label">제목 길이</div>
                        <div class="analysis-value">${titleLength}자 ${titleAnalysis.lengthStatus}</div>
                    </div>
                    <div class="analysis-item">
                        <div class="analysis-label">키워드 포함</div>
                        <div class="analysis-value">${titleAnalysis.keywordIncluded ? '✅ 포함됨' : '❌ 미포함'} - "${post.keyword || '-'}"</div>
                    </div>
                    <div class="analysis-tip">
                        <p>${titleAnalysis.tip}</p>
                    </div>
                </div>

                <div class="analysis-section">
                    <h4>🖼️ 이미지 분석</h4>
                    <div class="analysis-item">
                        <div class="analysis-label">이미지 수</div>
                        <div class="analysis-value">${post.images || 0}개 ${imageAnalysis.status}</div>
                    </div>
                    ${post.image_seo ? `
                    <div class="analysis-item">
                        <div class="analysis-label">ALT 태그 최적화</div>
                        <div class="analysis-value">${getAltQualityBadge(post.image_seo.alt_quality)} (${post.image_seo.with_alt || 0}/${post.image_seo.total_images || 0}개 설정됨)</div>
                    </div>
                    ${post.image_seo.recommendations && post.image_seo.recommendations.length > 0 ? `
                    <div class="analysis-tip">
                        <p>${post.image_seo.recommendations.join('<br>')}</p>
                    </div>
                    ` : ''}
                    ` : `
                    <div class="analysis-tip">
                        <p>${imageAnalysis.tip}</p>
                    </div>
                    `}
                </div>

                <div class="analysis-section">
                    <h4>📄 본문 분석</h4>
                    <div class="analysis-item">
                        <div class="analysis-label">글자 수</div>
                        <div class="analysis-value">${(post.char_count || 0).toLocaleString()}자 ${contentAnalysis.charStatus}</div>
                    </div>
                    <div class="analysis-item">
                        <div class="analysis-label">소제목 수</div>
                        <div class="analysis-value">${post.subheading_count || 0}개 ${contentAnalysis.subheadingStatus}</div>
                    </div>
                    <div class="analysis-item">
                        <div class="analysis-label">링크/동영상</div>
                        <div class="analysis-value">🔗 ${post.link_count || 0}개 ${post.has_video ? '/ 🎬 동영상 있음' : ''}</div>
                    </div>
                    <div class="analysis-tip">
                        <p>${contentAnalysis.tip}</p>
                    </div>
                </div>

                <div class="analysis-section">
                    <h4>🔍 노출 분석</h4>
                    <div class="analysis-item">
                        <div class="analysis-label">검색 노출 상태</div>
                        <div class="analysis-value">${exposureAnalysis.status}</div>
                    </div>
                    <div class="analysis-tip">
                        <p>${exposureAnalysis.tip}</p>
                    </div>
                </div>

                <div class="analysis-section">
                    <h4>💬 참여도 분석</h4>
                    <div class="analysis-item">
                        <div class="analysis-label">공감/댓글</div>
                        <div class="analysis-value">♥ ${post.likes || 0} / 💬 ${post.comments || 0} ${engagementAnalysis.status}</div>
                    </div>
                    <div class="analysis-tip">
                        <p>${engagementAnalysis.tip}</p>
                    </div>
                </div>

                <div class="analysis-section">
                    <h4>💡 종합 개선 조언</h4>
                    <div class="analysis-tip">
                        <p>${generateOverallAdvice(post, titleAnalysis, imageAnalysis, exposureAnalysis, engagementAnalysis)}</p>
                    </div>
                </div>
            `;

            modal.classList.add('active');
        }

        function analyzeTitleQuality(title, keyword) {
            const length = (title || '').length;
            let lengthStatus, tip;
            const keywordIncluded = keyword && title && title.includes(keyword);

            if (length < 15) {
                lengthStatus = '(너무 짧음 ⚠️)';
                tip = '제목이 너무 짧습니다. 검색 최적화를 위해 20-40자 사이의 제목을 권장합니다. 핵심 키워드를 포함하면서 구체적인 정보를 담아주세요.';
            } else if (length <= 25) {
                lengthStatus = '(적당함 ✅)';
                tip = '제목 길이가 적당합니다. 검색 결과에서 잘리지 않으면서 핵심을 전달하기 좋은 길이입니다.';
            } else if (length <= 40) {
                lengthStatus = '(양호 ✅)';
                tip = '제목이 충분한 정보를 담고 있습니다. 검색 결과에서 일부 잘릴 수 있으니 중요한 키워드는 앞쪽에 배치하세요.';
            } else {
                lengthStatus = '(다소 김 ⚠️)';
                tip = '제목이 다소 깁니다. 검색 결과에서 뒷부분이 잘릴 수 있으므로 핵심 키워드는 반드시 앞 30자 이내에 배치하세요.';
            }

            if (!keywordIncluded && keyword) {
                tip += ' 또한, 검색 키워드 "' + keyword + '"가 제목에 직접 포함되면 노출에 더 유리합니다.';
            }

            return { lengthStatus, keywordIncluded, tip };
        }

        // 이미지 ALT 품질 뱃지
        function getAltQualityBadge(quality) {
            const badges = {
                'excellent': '<span style="color: #81c784;">우수 ✅</span>',
                'good': '<span style="color: #7eb8ff;">양호 ✅</span>',
                'average': '<span style="color: #ffd54f;">보통 ⚠️</span>',
                'poor': '<span style="color: #e57373;">미흡 ❌</span>',
                'no_images': '<span style="color: #ffffff80;">이미지 없음</span>',
                'unknown': '<span style="color: #ffffff80;">분석 불가</span>'
            };
            return badges[quality] || badges['unknown'];
        }

        function analyzeImageCount(images) {
            let status, tip;

            if (images === 0) {
                status = '(없음 ❌)';
                tip = '이미지가 없습니다! 블로그 글에 최소 3-5개의 이미지를 추가하세요. 이미지가 없으면 검색 노출과 체류 시간에 불리합니다. 관련 이미지, 인포그래픽, 설명 캡처 등을 활용하세요.';
            } else if (images < 3) {
                status = '(부족 ⚠️)';
                tip = '이미지가 부족합니다. 최소 3-5개 이상의 이미지를 권장합니다. 글의 내용을 보완하는 고품질 이미지를 추가하여 독자의 이해도와 체류 시간을 높이세요.';
            } else if (images <= 7) {
                status = '(적당함 ✅)';
                tip = '적절한 이미지 수입니다. 이미지에 ALT 태그(대체 텍스트)를 키워드 포함하여 작성하면 이미지 검색 노출에도 도움이 됩니다.';
            } else if (images <= 15) {
                status = '(풍부함 ✅)';
                tip = '이미지가 풍부합니다! 체류 시간 증가에 도움이 됩니다. 다만 이미지 용량 최적화를 통해 페이지 로딩 속도를 관리하세요.';
            } else {
                status = '(매우 많음 ⚠️)';
                tip = '이미지가 매우 많습니다. 페이지 로딩 속도에 영향을 줄 수 있으니 이미지 압축과 최적화를 권장합니다. 정말 필요한 이미지인지 점검해보세요.';
            }

            return { status, tip };
        }

        function analyzeContent(charCount, subheadingCount, linkCount, hasVideo) {
            let charStatus, subheadingStatus, tip;
            let tips = [];

            // 글자 수 분석
            if (charCount < 500) {
                charStatus = '(매우 부족 ❌)';
                tips.push('글자 수가 너무 적습니다. 최소 1,500자 이상 작성을 권장합니다. 네이버는 충분한 정보를 담은 글을 선호합니다.');
            } else if (charCount < 1000) {
                charStatus = '(부족 ⚠️)';
                tips.push('글자 수가 부족합니다. 1,500자 이상으로 내용을 보강하세요.');
            } else if (charCount < 1500) {
                charStatus = '(보통)';
                tips.push('글자 수가 기본은 됩니다. 2,000자 이상이면 더 좋습니다.');
            } else if (charCount < 3000) {
                charStatus = '(적당함 ✅)';
                tips.push('좋은 글자 수입니다! 충분한 정보를 담고 있습니다.');
            } else {
                charStatus = '(풍부함 ✅)';
                tips.push('매우 풍부한 내용입니다! 체류 시간 증가에 도움이 됩니다.');
            }

            // 소제목 분석
            if (subheadingCount === 0) {
                subheadingStatus = '(없음 ⚠️)';
                tips.push('소제목이 없습니다. 2-5개의 소제목으로 글을 구조화하면 가독성이 높아집니다.');
            } else if (subheadingCount < 2) {
                subheadingStatus = '(부족)';
                tips.push('소제목을 더 추가하여 글의 구조를 명확히 하세요.');
            } else if (subheadingCount <= 5) {
                subheadingStatus = '(적당함 ✅)';
            } else {
                subheadingStatus = '(많음 ✅)';
            }

            // 동영상 보너스
            if (hasVideo) {
                tips.push('동영상이 포함되어 있어 체류 시간 증가에 도움이 됩니다!');
            }

            // 링크 분석
            if (linkCount > 10) {
                tips.push('외부 링크가 많습니다. 너무 많은 링크는 스팸으로 인식될 수 있으니 주의하세요.');
            }

            tip = tips.join(' ');

            return { charStatus, subheadingStatus, tip };
        }

        function analyzeExposure(exposure, keyword) {
            let status, tip;

            if (exposure === 'indexed') {
                status = '✅ 검색 노출됨';
                tip = '축하합니다! 이 글은 "' + (keyword || '키워드') + '" 검색 시 노출되고 있습니다. 지속적인 노출을 위해 글을 주기적으로 업데이트하고, 관련 글과 내부 링크를 연결하세요.';
            } else if (exposure === 'pending') {
                status = '⏳ 반영 대기중';
                tip = '아직 검색에 반영되지 않았습니다. 신규 글의 경우 24-72시간 정도 소요될 수 있습니다. 반영이 되지 않으면 키워드 경쟁도 확인과 제목/본문 최적화가 필요합니다.';
            } else {
                status = '❌ 미노출';
                tip = '검색 결과에 노출되지 않고 있습니다. 다음을 확인하세요: 1) 키워드 경쟁이 너무 치열한지 2) 제목에 키워드가 명확히 포함되어 있는지 3) 본문 내용이 충분한지(최소 1000자 이상 권장) 4) 저품질 판정을 받은 것은 아닌지.';
            }

            return { status, tip };
        }

        function analyzeEngagement(likes, comments) {
            const total = likes + comments;
            let status, tip;

            if (total === 0) {
                status = '(반응 없음 ⚠️)';
                tip = '아직 반응이 없습니다. 글 마지막에 질문을 던지거나 공감 유도 문구를 넣어보세요. 이웃 블로그에 먼저 소통하면 내 블로그에도 방문자가 늘어납니다.';
            } else if (total < 5) {
                status = '(낮음)';
                tip = '반응이 다소 적습니다. 흥미로운 썸네일, 가독성 좋은 본문 구성, 그리고 공감을 유도하는 마무리 멘트가 도움됩니다.';
            } else if (total < 15) {
                status = '(보통 ✅)';
                tip = '적당한 반응입니다. 댓글에 빠르게 답글을 달아 소통을 이어가세요. 활발한 소통은 블로그 지수에도 긍정적입니다.';
            } else if (total < 30) {
                status = '(좋음 ✅)';
                tip = '좋은 반응입니다! 이 글의 주제와 작성 방식을 분석하여 다른 글에도 적용해보세요.';
            } else {
                status = '(매우 좋음 🔥)';
                tip = '훌륭한 반응입니다! 이 글이 인기 있는 이유를 분석하고, 유사한 주제로 시리즈 글을 작성해보세요.';
            }

            return { status, tip };
        }

        function calculatePostScore(post) {
            let score = 0; // 기본 점수 0점 (업계 기준 엄격한 평가)

            // 제목 점수 (최대 15점) - 25-45자 최적
            const titleLen = (post.title || '').length;
            if (titleLen >= 25 && titleLen <= 45) score += 15;
            else if (titleLen >= 20 && titleLen <= 50) score += 10;
            else if (titleLen >= 15) score += 5;
            // 15자 미만은 0점

            // 이미지 점수 (최대 20점) - 업계 기준 6-13개 최적
            const images = post.images || 0;
            if (images >= 6 && images <= 13) score += 20;
            else if (images >= 4 && images <= 18) score += 12;
            else if (images >= 2) score += 5;
            // 1개 이하는 0점

            // 본문 점수 (최대 25점) - 업계 기준 2,500-3,000자 권장
            const charCount = post.char_count || 0;
            if (charCount >= 2500) score += 25;
            else if (charCount >= 2000) score += 18;
            else if (charCount >= 1500) score += 10;
            else if (charCount >= 1000) score += 5;
            // 1000자 미만은 0점

            // 소제목 점수 (최대 15점) - 업계 기준 4-5개 권장
            const subheadings = post.subheading_count || 0;
            if (subheadings >= 4) score += 15;
            else if (subheadings >= 3) score += 10;
            else if (subheadings >= 2) score += 6;
            else if (subheadings >= 1) score += 3;

            // 노출 점수 (최대 15점)
            if (post.exposure === 'indexed') score += 15;
            else if (post.exposure === 'pending') score += 5;
            // missing/unknown은 0점

            // 참여도 점수 (최대 10점)
            const engagement = (post.likes || 0) + (post.comments || 0);
            if (engagement >= 30) score += 10;
            else if (engagement >= 15) score += 6;
            else if (engagement >= 5) score += 3;

            return Math.max(0, Math.min(100, score));
        }

        function generateOverallAdvice(post, titleAnalysis, imageAnalysis, exposureAnalysis, engagementAnalysis) {
            const issues = [];
            const goods = [];

            // 제목 체크 (업계 기준: 25-45자)
            const titleLen = (post.title || '').length;
            if (titleLen < 20) issues.push('제목을 25자 이상으로 늘려주세요');
            else if (titleLen >= 25 && titleLen <= 45) goods.push('제목 길이 적절');
            else if (titleLen > 50) issues.push('제목이 너무 깁니다 (45자 이내 권장)');
            else goods.push('제목 길이 양호');

            if (!titleAnalysis.keywordIncluded && post.keyword) issues.push('제목에 핵심 키워드 포함 권장');

            // 이미지 체크 (업계 기준: 6-13개)
            const images = post.images || 0;
            if (images < 6) issues.push('이미지를 6개 이상 추가하세요');
            else if (images > 13) issues.push('이미지가 많습니다 (6-13개 권장)');
            else goods.push('이미지 수 적절');

            // 본문 체크 (업계 기준: 2,500자 이상)
            const charCount = post.char_count || 0;
            if (charCount < 1500) issues.push('본문을 2,500자 이상으로 보강하세요');
            else if (charCount < 2500) issues.push('본문 2,500자 이상 권장');
            else goods.push('본문 분량 충분');

            // 소제목 체크 (업계 기준: 4-5개)
            const subheadings = post.subheading_count || 0;
            if (subheadings === 0) issues.push('소제목(H2/H3)을 추가하여 가독성 높이기');
            else if (subheadings < 4) issues.push('소제목 4개 이상 권장');
            else goods.push('소제목 구성 적절');

            // 노출 체크
            if (post.exposure !== 'indexed') issues.push('검색 노출을 위한 최적화 필요');
            else goods.push('검색 노출 성공');

            // 참여도 체크
            if ((post.likes || 0) + (post.comments || 0) < 5) issues.push('공감/댓글 유도 필요');
            else goods.push('적절한 반응 유도');

            let advice = '';
            if (issues.length === 0) {
                advice = '🎉 훌륭합니다! 이 포스팅은 모든 항목에서 좋은 점수를 받았습니다. 이 패턴을 유지하며 꾸준히 포스팅하세요.';
            } else {
                advice = '📋 개선 포인트: ' + issues.join(', ') + '. ';
                if (goods.length > 0) {
                    advice += '👍 잘하고 있는 점: ' + goods.join(', ') + '.';
                }
            }

            return advice;
        }

        function closeAnalysisModal() {
            document.getElementById('analysisModal').classList.remove('active');
        }

        function closeModalOnOverlay(event) {
            if (event.target === document.getElementById('analysisModal')) {
                closeAnalysisModal();
            }
        }

        // 포스팅 지수 더보기 토글
        let postsExpanded = false;
        function toggleMorePosts() {
            const hiddenRows = document.querySelectorAll('.hidden-post-row');
            const btn = document.querySelector('.load-more-btn');
            const loadMoreText = document.getElementById('loadMoreText');

            postsExpanded = !postsExpanded;

            hiddenRows.forEach(row => {
                if (postsExpanded) {
                    row.classList.add('show');
                } else {
                    row.classList.remove('show');
                }
            });

            if (postsExpanded) {
                loadMoreText.textContent = '- 접기';
                btn.classList.add('expanded');
            } else {
                loadMoreText.textContent = '+ 더보기 (' + hiddenRows.length + '개)';
                btn.classList.remove('expanded');
            }
        }

        // 키워드 팝업 표시 함수 (ID로 호출)
        function showKeywordPopupById(idx) {
            const data = window['kwData_' + idx];
            if (data) {
                showKeywordPopup(data.keywords, data.title, data.mainKeyword, data.exposure);
            }
        }

        // 키워드 팝업 닫기
        function closeKeywordPopup() {
            const popup = document.getElementById('keywordPopup');
            if (popup) popup.remove();
        }

        // 키워드 팝업 표시 함수
        function showKeywordPopup(keywords, postTitle, mainKeyword, exposure) {
            // 기존 팝업 제거
            const existingPopup = document.getElementById('keywordPopup');
            if (existingPopup) existingPopup.remove();

            // 팝업 생성
            const popup = document.createElement('div');
            popup.id = 'keywordPopup';
            popup.style.cssText = 'position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: #000000b3; display: flex; justify-content: center; align-items: center; z-index: 10000;';
            popup.onclick = function(e) { if (e.target === popup) popup.remove(); };

            // 노출 상태 배지
            const exposureBadge = exposure === 'indexed' ?
                '<span style="background: #4caf5033; color: #81c784; padding: 2px 8px; border-radius: 4px; font-size: 10px; margin-left: 8px;">노출중</span>' :
                exposure === 'missing' ?
                '<span style="background: #f4433633; color: #e57373; padding: 2px 8px; border-radius: 4px; font-size: 10px; margin-left: 8px;">누락</span>' :
                '<span style="background: #ffc10733; color: #ffd54f; padding: 2px 8px; border-radius: 4px; font-size: 10px; margin-left: 8px;">확인중</span>';

            // 팝업 내용
            let keywordsList = keywords.map(function(kw) {
                const isMainKeyword = mainKeyword && kw.toLowerCase() === mainKeyword.toLowerCase();
                const badge = isMainKeyword ? exposureBadge : '';
                const bgColor = isMainKeyword && exposure === 'indexed' ? '#4caf501a' : 'transparent';
                return '<div style="display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid #ffffff1a; background: ' + bgColor + ';">' +
                    '<span style="font-size: 14px; font-weight: 500;">' + kw + badge + '</span>' +
                    '<a href="https://search.naver.com/search.naver?where=blog&query=' + encodeURIComponent(kw) + '" target="_blank" style="background: #667eea; color: white; padding: 6px 12px; border-radius: 6px; text-decoration: none; font-size: 12px; font-weight: 600;">검색 🔍</a>' +
                '</div>';
            }).join('');

            // 메인 키워드가 추출 키워드에 없으면 맨 위에 추가
            if (mainKeyword && !keywords.some(k => k.toLowerCase() === mainKeyword.toLowerCase())) {
                const bgColor = exposure === 'indexed' ? '#4caf501a' : 'transparent';
                keywordsList = '<div style="display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid #ffffff1a; background: ' + bgColor + ';">' +
                    '<span style="font-size: 14px; font-weight: 500;">' + mainKeyword + exposureBadge + '</span>' +
                    '<a href="https://search.naver.com/search.naver?where=blog&query=' + encodeURIComponent(mainKeyword) + '" target="_blank" style="background: #667eea; color: white; padding: 6px 12px; border-radius: 6px; text-decoration: none; font-size: 12px; font-weight: 600;">검색 🔍</a>' +
                '</div>' + keywordsList;
            }

            popup.innerHTML = '<div style="background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); border-radius: 16px; width: 90%; max-width: 400px; max-height: 80vh; overflow: hidden; box-shadow: 0 20px 60px #00000080;">' +
                '<div style="padding: 20px; border-bottom: 1px solid #ffffff1a;">' +
                    '<div style="display: flex; justify-content: space-between; align-items: center;">' +
                        '<h3 style="margin: 0; font-size: 16px; color: white;">🔍 추출 키워드</h3>' +
                        '<button onclick="closeKeywordPopup()" style="background: none; border: none; color: #ffffff99; font-size: 24px; cursor: pointer;">&times;</button>' +
                    '</div>' +
                    '<p style="margin: 8px 0 0 0; font-size: 12px; color: #ffffff80; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">' + (postTitle || '') + '</p>' +
                '</div>' +
                '<div style="max-height: 400px; overflow-y: auto;">' + keywordsList + '</div>' +
                '<div style="padding: 16px; border-top: 1px solid #ffffff1a; text-align: center;">' +
                    '<a href="https://search.naver.com/search.naver?where=blog&query=' + encodeURIComponent(keywords.join(' ')) + '" target="_blank" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 10px 24px; border-radius: 8px; text-decoration: none; font-size: 13px; font-weight: 600; display: inline-block;">전체 키워드로 검색</a>' +
                '</div>' +
            '</div>';

            document.body.appendChild(popup);
        }

        // 차트 렌더링 함수
        function renderCharts(data) {
            const idx = data.index || {};

            // 1. 지수 구성 도넛 차트
            const indexDonutCtx = document.getElementById('indexDonutChart');
            if (indexDonutCtx) {
                new Chart(indexDonutCtx, {
                    type: 'doughnut',
                    data: {
                        labels: ['노출 지수 (70%)', '활동 지수 (15%)', '신뢰 지수 (15%)'],
                        datasets: [{
                            data: [
                                idx.breakdown?.exposure || 0,
                                idx.breakdown?.activity || 0,
                                idx.breakdown?.trust || 0
                            ],
                            backgroundColor: [
                                '#667eeacc',
                                '#764ba2cc',
                                '#00e676cc'
                            ],
                            borderColor: [
                                '#667eea',
                                '#764ba2',
                                '#00e676'
                            ],
                            borderWidth: 2
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                position: 'bottom',
                                labels: {
                                    color: '#ffffffb3',
                                    font: { size: 11 },
                                    padding: 15
                                }
                            }
                        },
                        cutout: '60%'
                    }
                });
            }

            // 2. 노출 현황 파이 차트
            const exposureCtx = document.getElementById('exposureChart');
            if (exposureCtx && data.posts_with_index) {
                const exposureCounts = {
                    indexed: data.posts_with_index.filter(p => p.exposure === 'indexed').length,
                    missing: data.posts_with_index.filter(p => p.exposure === 'missing').length,
                    pending: data.posts_with_index.filter(p => p.exposure === 'pending' || p.exposure === 'unknown').length
                };

                new Chart(exposureCtx, {
                    type: 'pie',
                    data: {
                        labels: ['노출 ✓', '누락 ✗', '확인중'],
                        datasets: [{
                            data: [exposureCounts.indexed, exposureCounts.missing, exposureCounts.pending],
                            backgroundColor: [
                                '#4caf50cc',
                                '#f44336cc',
                                '#ffc107cc'
                            ],
                            borderColor: [
                                '#4caf50',
                                '#f44336',
                                '#ffc107'
                            ],
                            borderWidth: 2
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                position: 'bottom',
                                labels: {
                                    color: '#ffffffb3',
                                    font: { size: 11 },
                                    padding: 15
                                }
                            }
                        }
                    }
                });
            }

            // 3. 포스팅 반응 바 차트
            const engagementCtx = document.getElementById('engagementChart');
            if (engagementCtx && data.posts_with_index) {
                const posts = data.posts_with_index.slice(0, 10);
                const labels = posts.map((p, i) => (i + 1) + '. ' + (p.title || '').substring(0, 15) + '...');

                new Chart(engagementCtx, {
                    type: 'bar',
                    data: {
                        labels: labels,
                        datasets: [
                            {
                                label: '공감 ♥',
                                data: posts.map(p => p.likes || 0),
                                backgroundColor: '#f44336b3',
                                borderColor: '#f44336',
                                borderWidth: 1
                            },
                            {
                                label: '댓글 💬',
                                data: posts.map(p => p.comments || 0),
                                backgroundColor: '#2196f3b3',
                                borderColor: '#2196f3',
                                borderWidth: 1
                            },
                            {
                                label: '이미지 🖼',
                                data: posts.map(p => p.images || 0),
                                backgroundColor: '#4caf50b3',
                                borderColor: '#4caf50',
                                borderWidth: 1
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                position: 'top',
                                labels: {
                                    color: '#ffffffb3',
                                    font: { size: 11 },
                                    padding: 15
                                }
                            }
                        },
                        scales: {
                            x: {
                                ticks: {
                                    color: '#ffffff80',
                                    font: { size: 9 },
                                    maxRotation: 45
                                },
                                grid: { color: '#ffffff0d' }
                            },
                            y: {
                                ticks: { color: '#ffffff80' },
                                grid: { color: '#ffffff0d' }
                            }
                        }
                    }
                });
            }
        }

        // Enter 키 지원
        document.getElementById('blogId').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                analyzeBlog(e);
            }
        });
    </script>
</body>
</html>
'''


if __name__ == '__main__':
    print("=" * 50)
    print("🚀 블로그 지수 분석기 서버 시작!")
    print("=" * 50)
    print()
    print("📌 접속 주소: http://localhost:5001")
    print()
    print("💡 사용법:")
    print("   1. 위 주소로 브라우저에서 접속")
    print("   2. 블로그 아이디 입력 (예: loboking1)")
    print("   3. 분석하기 버튼 클릭")
    print()
    print("⏹️  종료하려면 Ctrl+C를 누르세요")
    print("=" * 50)

    app.run(host='0.0.0.0', port=5001, debug=True)
