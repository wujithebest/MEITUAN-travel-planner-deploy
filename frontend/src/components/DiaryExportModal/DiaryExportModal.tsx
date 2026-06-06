import React, { useRef, useState, useEffect, useCallback } from 'react';
import { Modal, Button, Space, message, Spin, Alert } from 'antd';
import { Download, Copy, X, Camera, Check, AlertCircle } from 'lucide-react';
import html2canvas from 'html2canvas';
import { useDiaryStore } from '@/store/diaryStore';
import DiaryPreview from '@/components/DiaryPreview/DiaryPreview';
import styles from './DiaryExportModal.module.css';

interface DiaryExportModalProps {
  visible: boolean;
  diaryId: string;
  mapInstance: any | null;
  onClose: () => void;
}

const DiaryExportModal: React.FC<DiaryExportModalProps> = ({
  visible,
  diaryId,
  mapInstance,
  onClose,
}) => {
  const diary = useDiaryStore((s) => s.diary);
  const mapScreenshot = useDiaryStore((s) => s.mapScreenshot);
  const isGeneratingImage = useDiaryStore((s) => s.isGeneratingImage);
  const hideExportModal = useDiaryStore((s) => s.hideExportModal);
  const setMapScreenshot = useDiaryStore((s) => s.setMapScreenshot);
  
  // 使用 diaryRef 绑定到包含实际内容的 DOM
  const diaryRef = useRef<HTMLDivElement>(null);
  const [capturing, setCapturing] = useState(false);
  const [previewReady, setPreviewReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [diaryLoading, setDiaryLoading] = useState(false);

  // 调试日志：监听 visible 变化
  useEffect(() => {
    console.log('[DiaryExportModal] visible 变化:', visible);
    if (visible) {
      console.log('[DiaryExportModal] diary 数据:', {
        hasDiary: !!diary,
        entriesCount: diary?.entries?.length,
        daysCount: diary?.stats?.total_days,
        diaryId
      });
      
      // 检查日记数据完整性
      if (diary) {
        validateDiaryData(diary);
      }
    }
  }, [visible, diary, diaryId]);
  
  // 验证日记数据完整性
  const validateDiaryData = (diaryData: any) => {
    const issues: string[] = [];
    
    if (!diaryData.entries || diaryData.entries.length === 0) {
      issues.push('日记条目为空');
    }
    
    if (!diaryData.stats || !diaryData.stats.total_days || diaryData.stats.total_days === 0) {
      issues.push('行程天数信息缺失');
    }
    
    if (issues.length > 0) {
      const errorMsg = `日记数据不完整: ${issues.join('; ')}`;
      console.warn('[DiaryExportModal]', errorMsg);
      setError(errorMsg);
    } else {
      setError(null);
    }
  };

  // 监听 visible 变化，弹窗打开时延迟生成预览
  useEffect(() => {
    if (!visible) {
      setPreviewReady(false);
      return;
    }

    console.log('[DiaryExportModal] 弹窗已打开，准备生成预览...');
    
    // 延迟 1 秒确保 DOM 已完全渲染
    const timer = setTimeout(() => {
      console.log('[DiaryExportModal] diaryRef.current:', diaryRef.current);
      
      if (diaryRef.current) {
        console.log('[DiaryExportModal] DOM 尺寸:', {
          scrollHeight: diaryRef.current.scrollHeight,
          scrollWidth: diaryRef.current.scrollWidth,
          clientHeight: diaryRef.current.clientHeight,
          clientWidth: diaryRef.current.clientWidth,
          innerHTML_length: diaryRef.current.innerHTML.length
        });
        
        // 检查图片是否设置了 crossOrigin
        const images = diaryRef.current.querySelectorAll('img');
        console.log('[DiaryExportModal] 图片数量:', images.length);
        images.forEach((img, idx) => {
          console.log(`[DiaryExportModal] 图片[${idx}]:`, {
            src: img.src?.substring(0, 50),
            crossOrigin: img.crossOrigin,
            complete: img.complete,
            naturalWidth: img.naturalWidth
          });
        });
        
        setPreviewReady(true);
      } else {
        console.error('[DiaryExportModal] diaryRef.current 为 null!');
      }
    }, 1000);

    return () => clearTimeout(timer);
  }, [visible]);

  // 截取地图
  const captureMap = useCallback(async () => {
    console.log('[DiaryExportModal] 开始截取地图...');
    setCapturing(true);
    
    try {
      // 尝试使用高德地图截图插件
      if (mapInstance && typeof mapInstance.getScreenshot === 'function') {
        console.log('[DiaryExportModal] 使用地图实例截图');
        // 高德地图 2.0+ 截图方法
        message.info('正在截取地图...');
      }
      
      // 备用方案：使用 html2canvas 截取地图容器
      const mapContainer = document.getElementById('gaode-map');
      if (mapContainer) {
        console.log('[DiaryExportModal] 找到地图容器，使用 html2canvas 截图');
        
        const canvas = await html2canvas(mapContainer, {
          useCORS: true,
          allowTaint: true,
          scale: 2,
          width: 300,
          height: 400,
          logging: true,
        });
        
        console.log('[DiaryExportModal] 地图截图 canvas:', {
          width: canvas.width,
          height: canvas.height
        });
        
        if (canvas.width === 0 || canvas.height === 0) {
          console.error('[DiaryExportModal] 地图截图 canvas 尺寸为 0!');
          throw new Error('截图尺寸为 0');
        }
        
        const dataURL = canvas.toDataURL('image/png');
        setMapScreenshot(dataURL);
        message.success('地图截图成功');
      } else {
        console.warn('[DiaryExportModal] 未找到地图容器 #gaode-map');
        message.warning('地图截图功能暂不可用，将生成无地图的日记图片');
      }
    } catch (error) {
      console.error('[DiaryExportModal] 截图失败:', error);
      message.error('截图失败');
    } finally {
      setCapturing(false);
    }
  }, [mapInstance, setMapScreenshot]);

  // 生成预览图片 - 使用 html2canvas
  const generatePreview = useCallback(async () => {
    console.log('[DiaryExportModal] ====== generatePreview 开始 ======');
    console.log('[DiaryExportModal] diaryRef.current:', diaryRef.current);
    
    if (!diaryRef.current) {
      console.error('[DiaryExportModal] diaryRef.current 为 null，无法生成预览');
      message.error('预览区域未就绪');
      return null;
    }

    console.log('[DiaryExportModal] DOM 检查:', {
      scrollHeight: diaryRef.current.scrollHeight,
      scrollWidth: diaryRef.current.scrollWidth,
      innerHTML_length: diaryRef.current.innerHTML.length
    });

    if (diaryRef.current.scrollHeight === 0) {
      console.error('[DiaryExportModal] DOM scrollHeight 为 0，内容可能未渲染');
      message.error('日记内容未完全加载，请稍后重试');
      return null;
    }

    useDiaryStore.setState({ isGeneratingImage: true });
    
    try {
      console.log('[DiaryExportModal] 开始调用 html2canvas...');
      
      const canvas = await html2canvas(diaryRef.current, {
        scale: 2,
        useCORS: true,
        allowTaint: true,
        height: diaryRef.current.scrollHeight,
        windowHeight: diaryRef.current.scrollHeight,
        backgroundColor: '#ffffff',
        logging: false,
        removeContainer: true,
      });

      console.log('[DiaryExportModal] html2canvas 返回 canvas:', {
        width: canvas.width,
        height: canvas.height
      });

      if (canvas.width === 0 || canvas.height === 0) {
        console.error('[DiaryExportModal] canvas 尺寸为 0!');
        throw new Error('生成的图片尺寸为 0');
      }

      const dataURL = canvas.toDataURL('image/png');
      console.log('[DiaryExportModal] 图片生成成功, dataURL length:', dataURL.length);
      
      return dataURL;
    } catch (error) {
      console.error('[DiaryExportModal] 生成图片失败:', error);
      message.error('生成图片失败');
      return null;
    } finally {
      useDiaryStore.setState({ isGeneratingImage: false });
      console.log('[DiaryExportModal] ====== generatePreview 结束 ======');
    }
  }, []);

  // 保存日记图片
  const handleSaveImage = async () => {
    console.log('[DiaryExportModal] 点击保存图片按钮');
    
    const dataURL = await generatePreview();
    if (!dataURL) {
      console.error('[DiaryExportModal] 预览图片生成失败');
      return;
    }

    // 创建下载链接
    const link = document.createElement('a');
    const dateStr = new Date().toISOString().slice(0, 10).replace(/-/g, '');
    link.download = `旅行日记_${dateStr}.png`;
    link.href = dataURL;
    link.click();
    
    message.success('日记图片已保存');
  };

  // 复制分享文案
  const handleCopyShareText = async () => {
    if (!diary) return;

    const stats = diary.stats || {};
    const text = `🎉 我刚完成了一次${stats.total_days || 0}天的旅行！\n\n` +
      `📍 途经 ${stats.cities_visited || 0} 个城市\n` +
      `🚗 总里程 ${stats.total_distance || 0}km\n` +
      `📸 拍摄 ${stats.total_photos || 0} 张照片\n` +
      `🏛️ 打卡 ${stats.pois_visited || 0} 个地点\n\n` +
      `快来看看我的旅行日记吧！`;

    try {
      await navigator.clipboard.writeText(text);
      message.success('分享文案已复制到剪贴板');
    } catch (error) {
      console.error('复制失败:', error);
      message.error('复制失败');
    }
  };

  // 关闭弹窗
  const handleClose = () => {
    hideExportModal();
    onClose();
  };

  if (!diary) {
    console.log('[DiaryExportModal] diary 为 null，不渲染');
    return null;
  }

  return (
    <Modal
      title="🎉 您的旅行日记已生成"
      open={visible}
      onCancel={handleClose}
      footer={null}
      width={900}
      centered
      className={styles.modal}
      zIndex={1100}
    >
      {/* 错误提示 */}
      {error && (
        <div className={styles.errorSection}>
          <Alert
            message="数据异常"
            description={error}
            type="warning"
            showIcon
            icon={<AlertCircle size={16} />}
            closable
            onClose={() => setError(null)}
          />
        </div>
      )}

      <div className={styles.container}>
        {/* 左栏：日记预览 */}
        <div className={styles.leftColumn}>
          <Spin spinning={isGeneratingImage} tip="正在生成预览...">
            <div className={styles.previewWrapper}>
              {/* diaryRef 绑定到包含实际内容的 DOM */}
              <div 
                ref={diaryRef} 
                className={styles.previewContent}
                data-testid="diary-preview-content"
              >
                <DiaryPreview diary={diary} mapScreenshot={mapScreenshot} />
              </div>
            </div>
          </Spin>
        </div>

        {/* 右栏：地图截图 */}
        <div className={styles.rightColumn}>
          <div className={styles.mapSection}>
            <h4>地图截图</h4>
            
            {mapScreenshot ? (
              <div className={styles.screenshotPreview}>
                <img 
                  src={mapScreenshot} 
                  alt="地图截图" 
                  crossOrigin="anonymous"
                />
                <div className={styles.screenshotActions}>
                  <Button
                    size="small"
                    icon={<Camera size={14} />}
                    onClick={captureMap}
                    loading={capturing}
                  >
                    重截
                  </Button>
                  <Button
                    size="small"
                    type="primary"
                    icon={<Check size={14} />}
                    disabled
                  >
                    已确认
                  </Button>
                </div>
              </div>
            ) : (
              <div className={styles.mapPlaceholder}>
                <Spin spinning={capturing}>
                  <div className={styles.placeholderContent}>
                    <Camera size={48} />
                    <p>点击下方按钮截取地图</p>
                    <Button
                      type="primary"
                      icon={<Camera size={16} />}
                      onClick={captureMap}
                      loading={capturing}
                    >
                      截取当前地图
                    </Button>
                  </div>
                </Spin>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 底部按钮栏 */}
      <div className={styles.footer}>
        <Space size="middle">
          <Button
            type="primary"
            icon={<Download size={16} />}
            onClick={handleSaveImage}
            loading={isGeneratingImage}
            size="large"
          >
            保存日记图片
          </Button>
          <Button
            icon={<Copy size={16} />}
            onClick={handleCopyShareText}
            size="large"
          >
            复制分享文案
          </Button>
          <Button
            icon={<X size={16} />}
            onClick={handleClose}
            size="large"
          >
            关闭
          </Button>
        </Space>
      </div>
    </Modal>
  );
};

export default DiaryExportModal;
