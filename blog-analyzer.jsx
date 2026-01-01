import React, { useState } from 'react';
import { Search, TrendingUp, Users, FileText, Eye, Heart, MessageCircle, BarChart3, CheckCircle, AlertTriangle, XCircle, Zap, Calendar, Award } from 'lucide-react';

// 블로그 지수 계산 알고리즘 (자체 개발)
const calculateBlogIndex = (data) => {
  // 방문자 점수 (최대 30점)
  const visitorScore = Math.min(30, (data.dailyVisitors / 1000) * 10);
  
  // 이웃 점수 (최대 20점)
  const neighborScore = Math.min(20, (data.neighbors / 500) * 10);
  
  // 포스팅 점수 (최대 20점)
  const postScore = Math.min(20, (data.totalPosts / 500) * 10);
  
  // 활동성 점수 (최대 15점)
  const activityScore = Math.min(15, data.postsPerWeek * 3);
  
  // 인게이지먼트 점수 (최대 15점)
  const engagementScore = Math.min(15, (data.avgComments + data.avgLikes) / 10);
  
  const totalScore = visitorScore + neighborScore + postScore + activityScore + engagementScore;
  
  // 등급 결정
  if (totalScore >= 85) return { grade: '최적1+', level: 'optimal-plus', score: totalScore, color: '#FFD700' };
  if (totalScore >= 75) return { grade: '최적1', level: 'optimal', score: totalScore, color: '#00E676' };
  if (totalScore >= 65) return { grade: '최적2', level: 'optimal2', score: totalScore, color: '#00E676' };
  if (totalScore >= 55) return { grade: '준최1', level: 'semi1', score: totalScore, color: '#2196F3' };
  if (totalScore >= 45) return { grade: '준최2', level: 'semi2', score: totalScore, color: '#2196F3' };
  if (totalScore >= 35) return { grade: '준최3', level: 'semi3', score: totalScore, color: '#FF9800' };
  if (totalScore >= 25) return { grade: '준최4', level: 'semi4', score: totalScore, color: '#FF9800' };
  return { grade: '일반', level: 'normal', score: totalScore, color: '#9E9E9E' };
};

// 데모 블로그 데이터 생성
const generateDemoData = (blogId) => {
  const seed = blogId.length * 7 + blogId.charCodeAt(0);
  const random = (min, max) => Math.floor((Math.sin(seed * Math.random()) + 1) / 2 * (max - min) + min);
  
  return {
    blogId,
    blogName: `${blogId}의 블로그`,
    profileImage: `https://picsum.photos/seed/${blogId}/100/100`,
    dailyVisitors: random(100, 5000),
    totalVisitors: random(50000, 500000),
    neighbors: random(50, 2000),
    mutualNeighbors: random(30, 500),
    totalPosts: random(100, 1500),
    postsPerWeek: random(1, 7),
    avgComments: random(5, 50),
    avgLikes: random(10, 100),
    blogAge: random(1, 10),
    recentPosts: [
      { title: '오늘의 일상 기록', date: '2025-12-30', views: random(100, 1000), comments: random(5, 30), index: random(60, 90) },
      { title: '맛집 탐방 후기', date: '2025-12-28', views: random(200, 2000), comments: random(10, 50), index: random(55, 85) },
      { title: '제품 리뷰', date: '2025-12-25', views: random(150, 1500), comments: random(8, 40), index: random(50, 80) },
      { title: '여행 이야기', date: '2025-12-22', views: random(300, 3000), comments: random(15, 60), index: random(65, 95) },
      { title: '취미 생활', date: '2025-12-20', views: random(80, 800), comments: random(3, 25), index: random(45, 75) },
    ],
    visitorHistory: Array.from({ length: 7 }, (_, i) => ({
      date: `12/${24 + i}`,
      visitors: random(100, 5000)
    }))
  };
};

const BlogAnalyzer = () => {
  const [blogUrl, setBlogUrl] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');

  const analyzeBlog = async () => {
    if (!blogUrl.trim()) {
      setError('블로그 주소 또는 아이디를 입력해주세요.');
      return;
    }

    setAnalyzing(true);
    setError('');
    setResult(null);

    // 블로그 ID 추출
    let blogId = blogUrl.trim();
    if (blogId.includes('blog.naver.com/')) {
      blogId = blogId.split('blog.naver.com/')[1].split(/[?/]/)[0];
    }

    // 분석 시뮬레이션 (실제로는 백엔드 API 호출)
    await new Promise(resolve => setTimeout(resolve, 2000));

    const data = generateDemoData(blogId);
    const indexResult = calculateBlogIndex(data);
    
    setResult({ ...data, index: indexResult });
    setAnalyzing(false);
  };

  const getIndexBarWidth = (score) => `${Math.min(100, score)}%`;

  return (
    <div style={{
      minHeight: '100vh',
      background: 'linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #16213e 100%)',
      fontFamily: '"Pretendard", "Noto Sans KR", -apple-system, BlinkMacSystemFont, sans-serif',
      color: '#ffffff',
      padding: '0',
      margin: '0'
    }}>
      {/* Header */}
      <header style={{
        background: 'rgba(255,255,255,0.03)',
        borderBottom: '1px solid rgba(255,255,255,0.1)',
        padding: '16px 24px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        backdropFilter: 'blur(10px)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            width: '40px',
            height: '40px',
            borderRadius: '12px',
            background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}>
            <BarChart3 size={24} color="#fff" />
          </div>
          <div>
            <h1 style={{ margin: 0, fontSize: '20px', fontWeight: '700', letterSpacing: '-0.5px' }}>
              블로그 지수 분석기
            </h1>
            <p style={{ margin: 0, fontSize: '12px', color: 'rgba(255,255,255,0.5)' }}>
              Blog Index Analyzer
            </p>
          </div>
        </div>
        <div style={{
          padding: '8px 16px',
          background: 'rgba(102, 126, 234, 0.2)',
          borderRadius: '20px',
          fontSize: '12px',
          color: '#667eea'
        }}>
          🔬 데모 버전
        </div>
      </header>

      {/* Main Content */}
      <main style={{ maxWidth: '1200px', margin: '0 auto', padding: '40px 24px' }}>
        
        {/* Search Section */}
        <section style={{
          background: 'rgba(255,255,255,0.05)',
          borderRadius: '24px',
          padding: '40px',
          marginBottom: '32px',
          border: '1px solid rgba(255,255,255,0.1)',
          textAlign: 'center'
        }}>
          <h2 style={{ 
            fontSize: '28px', 
            fontWeight: '700', 
            marginBottom: '12px',
            background: 'linear-gradient(90deg, #667eea 0%, #764ba2 50%, #f093fb 100%)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent'
          }}>
            네이버 블로그 지수 조회
          </h2>
          <p style={{ color: 'rgba(255,255,255,0.6)', marginBottom: '32px', fontSize: '15px' }}>
            블로그 주소 또는 아이디를 입력하면 지수를 분석해드립니다
          </p>
          
          <div style={{
            display: 'flex',
            gap: '12px',
            maxWidth: '600px',
            margin: '0 auto'
          }}>
            <div style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              background: 'rgba(255,255,255,0.08)',
              borderRadius: '16px',
              padding: '4px 4px 4px 20px',
              border: '2px solid rgba(102, 126, 234, 0.3)',
              transition: 'all 0.3s ease'
            }}>
              <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: '14px', whiteSpace: 'nowrap' }}>
                blog.naver.com/
              </span>
              <input
                type="text"
                value={blogUrl}
                onChange={(e) => setBlogUrl(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && analyzeBlog()}
                placeholder="블로그 아이디 입력"
                style={{
                  flex: 1,
                  background: 'transparent',
                  border: 'none',
                  outline: 'none',
                  color: '#fff',
                  fontSize: '16px',
                  padding: '16px 12px'
                }}
              />
            </div>
            <button
              onClick={analyzeBlog}
              disabled={analyzing}
              style={{
                padding: '0 32px',
                background: analyzing 
                  ? 'rgba(102, 126, 234, 0.5)' 
                  : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                border: 'none',
                borderRadius: '16px',
                color: '#fff',
                fontSize: '16px',
                fontWeight: '600',
                cursor: analyzing ? 'not-allowed' : 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                transition: 'all 0.3s ease',
                boxShadow: analyzing ? 'none' : '0 4px 20px rgba(102, 126, 234, 0.4)'
              }}
            >
              {analyzing ? (
                <>
                  <div style={{
                    width: '20px',
                    height: '20px',
                    border: '2px solid rgba(255,255,255,0.3)',
                    borderTopColor: '#fff',
                    borderRadius: '50%',
                    animation: 'spin 1s linear infinite'
                  }} />
                  분석 중...
                </>
              ) : (
                <>
                  <Search size={20} />
                  분석하기
                </>
              )}
            </button>
          </div>
          
          {error && (
            <p style={{ color: '#ff6b6b', marginTop: '16px', fontSize: '14px' }}>
              ⚠️ {error}
            </p>
          )}
        </section>

        {/* Results Section */}
        {result && (
          <div style={{ animation: 'fadeIn 0.5s ease' }}>
            
            {/* Blog Profile Card */}
            <section style={{
              background: 'rgba(255,255,255,0.05)',
              borderRadius: '24px',
              padding: '32px',
              marginBottom: '24px',
              border: '1px solid rgba(255,255,255,0.1)',
              display: 'grid',
              gridTemplateColumns: 'auto 1fr auto',
              gap: '32px',
              alignItems: 'center'
            }}>
              <div style={{
                width: '100px',
                height: '100px',
                borderRadius: '50%',
                background: `url(${result.profileImage}) center/cover`,
                border: '4px solid',
                borderColor: result.index.color,
                boxShadow: `0 0 30px ${result.index.color}40`
              }} />
              
              <div>
                <h3 style={{ margin: '0 0 8px 0', fontSize: '24px', fontWeight: '700' }}>
                  {result.blogName}
                </h3>
                <p style={{ margin: 0, color: 'rgba(255,255,255,0.5)', fontSize: '14px' }}>
                  blog.naver.com/{result.blogId}
                </p>
                <div style={{ display: 'flex', gap: '24px', marginTop: '16px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'rgba(255,255,255,0.7)' }}>
                    <Calendar size={16} />
                    <span>{result.blogAge}년차 블로그</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'rgba(255,255,255,0.7)' }}>
                    <FileText size={16} />
                    <span>총 {result.totalPosts.toLocaleString()}개 포스팅</span>
                  </div>
                </div>
              </div>
              
              {/* Index Badge */}
              <div style={{
                textAlign: 'center',
                padding: '24px 32px',
                background: `linear-gradient(135deg, ${result.index.color}20 0%, ${result.index.color}10 100%)`,
                borderRadius: '20px',
                border: `2px solid ${result.index.color}50`
              }}>
                <div style={{ fontSize: '14px', color: 'rgba(255,255,255,0.6)', marginBottom: '8px' }}>
                  블로그 지수
                </div>
                <div style={{
                  fontSize: '36px',
                  fontWeight: '800',
                  color: result.index.color,
                  textShadow: `0 0 20px ${result.index.color}80`
                }}>
                  {result.index.grade}
                </div>
                <div style={{
                  marginTop: '8px',
                  padding: '4px 12px',
                  background: 'rgba(255,255,255,0.1)',
                  borderRadius: '12px',
                  fontSize: '12px'
                }}>
                  점수: {result.index.score.toFixed(1)} / 100
                </div>
              </div>
            </section>

            {/* Stats Grid */}
            <section style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(4, 1fr)',
              gap: '16px',
              marginBottom: '24px'
            }}>
              {[
                { icon: Eye, label: '일일 방문자', value: result.dailyVisitors.toLocaleString(), color: '#667eea' },
                { icon: Users, label: '이웃 수', value: result.neighbors.toLocaleString(), color: '#f093fb' },
                { icon: Heart, label: '평균 공감', value: result.avgLikes.toLocaleString(), color: '#ff6b6b' },
                { icon: MessageCircle, label: '평균 댓글', value: result.avgComments.toLocaleString(), color: '#00E676' }
              ].map((stat, i) => (
                <div key={i} style={{
                  background: 'rgba(255,255,255,0.05)',
                  borderRadius: '20px',
                  padding: '24px',
                  border: '1px solid rgba(255,255,255,0.1)',
                  textAlign: 'center'
                }}>
                  <div style={{
                    width: '48px',
                    height: '48px',
                    borderRadius: '14px',
                    background: `${stat.color}20`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    margin: '0 auto 12px'
                  }}>
                    <stat.icon size={24} color={stat.color} />
                  </div>
                  <div style={{ fontSize: '24px', fontWeight: '700', marginBottom: '4px' }}>
                    {stat.value}
                  </div>
                  <div style={{ fontSize: '13px', color: 'rgba(255,255,255,0.5)' }}>
                    {stat.label}
                  </div>
                </div>
              ))}
            </section>

            {/* Index Progress */}
            <section style={{
              background: 'rgba(255,255,255,0.05)',
              borderRadius: '24px',
              padding: '32px',
              marginBottom: '24px',
              border: '1px solid rgba(255,255,255,0.1)'
            }}>
              <h3 style={{ margin: '0 0 24px 0', fontSize: '18px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Award size={20} color="#667eea" />
                지수 등급 현황
              </h3>
              
              <div style={{ position: 'relative', marginBottom: '32px' }}>
                <div style={{
                  height: '12px',
                  background: 'rgba(255,255,255,0.1)',
                  borderRadius: '6px',
                  overflow: 'hidden'
                }}>
                  <div style={{
                    height: '100%',
                    width: getIndexBarWidth(result.index.score),
                    background: `linear-gradient(90deg, ${result.index.color}, ${result.index.color}aa)`,
                    borderRadius: '6px',
                    transition: 'width 1s ease',
                    boxShadow: `0 0 20px ${result.index.color}60`
                  }} />
                </div>
                
                {/* Grade Labels */}
                <div style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  marginTop: '12px',
                  fontSize: '11px',
                  color: 'rgba(255,255,255,0.4)'
                }}>
                  <span>일반</span>
                  <span>준최4</span>
                  <span>준최3</span>
                  <span>준최2</span>
                  <span>준최1</span>
                  <span>최적2</span>
                  <span>최적1</span>
                  <span>최적1+</span>
                </div>
              </div>

              {/* Score Breakdown */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(5, 1fr)',
                gap: '12px'
              }}>
                {[
                  { label: '방문자', max: 30, value: Math.min(30, (result.dailyVisitors / 1000) * 10) },
                  { label: '이웃', max: 20, value: Math.min(20, (result.neighbors / 500) * 10) },
                  { label: '포스팅', max: 20, value: Math.min(20, (result.totalPosts / 500) * 10) },
                  { label: '활동성', max: 15, value: Math.min(15, result.postsPerWeek * 3) },
                  { label: '인게이지먼트', max: 15, value: Math.min(15, (result.avgComments + result.avgLikes) / 10) }
                ].map((item, i) => (
                  <div key={i} style={{
                    background: 'rgba(255,255,255,0.05)',
                    borderRadius: '12px',
                    padding: '16px',
                    textAlign: 'center'
                  }}>
                    <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.5)', marginBottom: '8px' }}>
                      {item.label}
                    </div>
                    <div style={{ fontSize: '20px', fontWeight: '700', color: '#667eea' }}>
                      {item.value.toFixed(1)}
                    </div>
                    <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.3)' }}>
                      / {item.max}점
                    </div>
                  </div>
                ))}
              </div>
            </section>

            {/* Recent Posts Analysis */}
            <section style={{
              background: 'rgba(255,255,255,0.05)',
              borderRadius: '24px',
              padding: '32px',
              marginBottom: '24px',
              border: '1px solid rgba(255,255,255,0.1)'
            }}>
              <h3 style={{ margin: '0 0 24px 0', fontSize: '18px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <FileText size={20} color="#f093fb" />
                최근 포스팅 분석
              </h3>
              
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {result.recentPosts.map((post, i) => (
                  <div key={i} style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr auto auto auto',
                    gap: '24px',
                    alignItems: 'center',
                    padding: '16px 20px',
                    background: 'rgba(255,255,255,0.03)',
                    borderRadius: '12px',
                    border: '1px solid rgba(255,255,255,0.05)'
                  }}>
                    <div>
                      <div style={{ fontWeight: '500', marginBottom: '4px' }}>{post.title}</div>
                      <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.4)' }}>{post.date}</div>
                    </div>
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ fontSize: '14px', fontWeight: '600' }}>{post.views.toLocaleString()}</div>
                      <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.4)' }}>조회</div>
                    </div>
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ fontSize: '14px', fontWeight: '600' }}>{post.comments}</div>
                      <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.4)' }}>댓글</div>
                    </div>
                    <div style={{
                      padding: '6px 12px',
                      borderRadius: '8px',
                      fontSize: '13px',
                      fontWeight: '600',
                      background: post.index >= 70 ? 'rgba(0, 230, 118, 0.2)' : post.index >= 50 ? 'rgba(33, 150, 243, 0.2)' : 'rgba(255, 152, 0, 0.2)',
                      color: post.index >= 70 ? '#00E676' : post.index >= 50 ? '#2196F3' : '#FF9800'
                    }}>
                      {post.index >= 70 ? '최적' : post.index >= 50 ? '준최' : '일반'}
                    </div>
                  </div>
                ))}
              </div>
            </section>

            {/* Visitor Chart */}
            <section style={{
              background: 'rgba(255,255,255,0.05)',
              borderRadius: '24px',
              padding: '32px',
              border: '1px solid rgba(255,255,255,0.1)'
            }}>
              <h3 style={{ margin: '0 0 24px 0', fontSize: '18px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <TrendingUp size={20} color="#00E676" />
                최근 7일 방문자 추이
              </h3>
              
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: '12px', height: '200px' }}>
                {result.visitorHistory.map((day, i) => {
                  const maxVisitors = Math.max(...result.visitorHistory.map(d => d.visitors));
                  const height = (day.visitors / maxVisitors) * 160;
                  return (
                    <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
                      <div style={{ fontSize: '12px', color: '#667eea', fontWeight: '600' }}>
                        {day.visitors.toLocaleString()}
                      </div>
                      <div style={{
                        width: '100%',
                        height: `${height}px`,
                        background: 'linear-gradient(180deg, #667eea 0%, #764ba2 100%)',
                        borderRadius: '8px 8px 4px 4px',
                        transition: 'height 0.5s ease',
                        boxShadow: '0 4px 20px rgba(102, 126, 234, 0.3)'
                      }} />
                      <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.5)' }}>
                        {day.date}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          </div>
        )}

        {/* Info Section */}
        {!result && !analyzing && (
          <section style={{
            background: 'rgba(255,255,255,0.03)',
            borderRadius: '24px',
            padding: '40px',
            border: '1px solid rgba(255,255,255,0.08)',
            marginTop: '32px'
          }}>
            <h3 style={{ 
              fontSize: '20px', 
              fontWeight: '600', 
              marginBottom: '24px',
              display: 'flex',
              alignItems: 'center',
              gap: '12px'
            }}>
              <Zap size={24} color="#FFD700" />
              블로그 지수란?
            </h3>
            
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(2, 1fr)',
              gap: '24px'
            }}>
              <div>
                <h4 style={{ color: '#667eea', marginBottom: '12px', fontSize: '16px' }}>📊 지수 등급 체계</h4>
                <ul style={{ 
                  listStyle: 'none', 
                  padding: 0, 
                  margin: 0,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '8px'
                }}>
                  {[
                    { grade: '최적1+', desc: '상위 1% 블로그', color: '#FFD700' },
                    { grade: '최적1~2', desc: '상위 5% 블로그', color: '#00E676' },
                    { grade: '준최1~4', desc: '상위 30% 블로그', color: '#2196F3' },
                    { grade: '일반', desc: '기본 등급', color: '#9E9E9E' }
                  ].map((item, i) => (
                    <li key={i} style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '12px',
                      padding: '8px 12px',
                      background: 'rgba(255,255,255,0.03)',
                      borderRadius: '8px'
                    }}>
                      <span style={{
                        width: '12px',
                        height: '12px',
                        borderRadius: '50%',
                        background: item.color
                      }} />
                      <span style={{ fontWeight: '600', color: item.color }}>{item.grade}</span>
                      <span style={{ color: 'rgba(255,255,255,0.5)', fontSize: '13px' }}>{item.desc}</span>
                    </li>
                  ))}
                </ul>
              </div>
              
              <div>
                <h4 style={{ color: '#f093fb', marginBottom: '12px', fontSize: '16px' }}>🎯 측정 항목</h4>
                <ul style={{ 
                  listStyle: 'none', 
                  padding: 0, 
                  margin: 0,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '8px',
                  color: 'rgba(255,255,255,0.7)',
                  fontSize: '14px'
                }}>
                  <li>✓ 일일 방문자 수 (30점)</li>
                  <li>✓ 이웃/서로이웃 수 (20점)</li>
                  <li>✓ 총 포스팅 수 (20점)</li>
                  <li>✓ 포스팅 활동성 (15점)</li>
                  <li>✓ 댓글/공감 인게이지먼트 (15점)</li>
                </ul>
              </div>
            </div>
            
            <div style={{
              marginTop: '32px',
              padding: '20px',
              background: 'rgba(102, 126, 234, 0.1)',
              borderRadius: '12px',
              border: '1px solid rgba(102, 126, 234, 0.2)'
            }}>
              <p style={{ margin: 0, fontSize: '14px', color: 'rgba(255,255,255,0.7)', lineHeight: '1.7' }}>
                ⚠️ <strong>참고:</strong> 이 도구는 데모 버전입니다. 실제 서비스로 운영하려면 네이버 블로그 데이터를 
                크롤링하는 백엔드 서버가 필요합니다. 현재는 입력한 블로그 ID를 기반으로 
                시뮬레이션된 데이터를 보여드립니다.
              </p>
            </div>
          </section>
        )}
      </main>

      {/* CSS Animation */}
      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(20px); }
          to { opacity: 1; transform: translateY(0); }
        }
        input::placeholder {
          color: rgba(255,255,255,0.3);
        }
      `}</style>
    </div>
  );
};

export default BlogAnalyzer;
