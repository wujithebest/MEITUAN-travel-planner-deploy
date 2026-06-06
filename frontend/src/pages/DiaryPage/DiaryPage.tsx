import React, { useRef, useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Layout, Button, Space } from 'antd';
import { ArrowLeft, Download, Share2, Edit } from 'lucide-react';
import { DiaryPreview, DiaryEditor, DiaryExportModal, LoadingOverlay } from '@/components';
import { useDiaryStore } from '@/store/diaryStore';
import { useDiary } from '@/hooks/useDiary';
import styles from './DiaryPage.module.css';

const { Header, Content } = Layout;

const DiaryPage: React.FC = () => {
  const { diaryId } = useParams<{ diaryId: string }>();
  const navigate = useNavigate();
  const diaryRef = useRef<HTMLDivElement>(null);
  const [editing, setEditing] = useState(false);
  
  const diary = useDiaryStore((s) => s.diary);
  const generating = useDiaryStore((s) => s.generating);
  const exportModalVisible = useDiaryStore((s) => s.exportModalVisible);
  const hideExportModal = useDiaryStore((s) => s.hideExportModal);
  const { load } = useDiary();

  useEffect(() => {
    if (diaryId) load(diaryId);
  }, [diaryId, load]);

  if (!diary && !generating) {
    return (
      <div className={styles.empty}>
        <p>日记不存在或加载中...</p>
        <Button onClick={() => navigate('/')}>返回首页</Button>
      </div>
    );
  }

  return (
    <Layout className={styles.layout}>
      <Header className={styles.header}>
        <Button icon={<ArrowLeft size={16} />} onClick={() => navigate('/')}>
          返回
        </Button>
        <Space>
          <Button icon={<Edit size={16} />} onClick={() => setEditing(!editing)}>
            {editing ? '预览' : '编辑'}
          </Button>
          <Button icon={<Download size={16} />} onClick={() => useDiaryStore.getState().showExportModal()}>
            导出
          </Button>
          <Button icon={<Share2 size={16} />} type="primary">
            分享
          </Button>
        </Space>
      </Header>

      <Content className={styles.content}>
        {editing ? (
          <div className={styles.editorContainer}>
            {diary && <DiaryEditor day={1} />}
          </div>
        ) : (
          <div ref={diaryRef} className={styles.previewContainer}>
            {diary && <DiaryPreview diary={diary} />}
          </div>
        )}
      </Content>

      {/* 新的日记导出弹窗 */}
      {diary && (
        <DiaryExportModal
          visible={exportModalVisible}
          diaryId={diary.id}
          mapInstance={null} // DiaryPage 中暂时不传地图实例，使用备用截图方案
          onClose={hideExportModal}
        />
      )}

      <LoadingOverlay visible={generating} tip="正在生成日记..." />
    </Layout>
  );
};

export default DiaryPage;
