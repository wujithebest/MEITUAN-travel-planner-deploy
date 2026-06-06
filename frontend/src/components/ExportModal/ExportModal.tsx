import React, { useState } from 'react';
import { Modal, Button, Space, Progress } from 'antd';
import { Download, FileImage, FileText, Share2 } from 'lucide-react';
import html2canvas from 'html2canvas';
import { jsPDF } from 'jspdf';
import { useDiary } from '@/hooks/useDiary';
import styles from './ExportModal.module.css';

interface ExportModalProps {
  visible: boolean;
  diaryId: string;
  targetRef: React.RefObject<HTMLElement>;
  onClose: () => void;
}

const ExportModal: React.FC<ExportModalProps> = ({ visible, diaryId, targetRef, onClose }) => {
  const [exporting, setExporting] = useState(false);
  const [progress, setProgress] = useState(0);
  const { export: exportDiary, share } = useDiary();

  const handleExportImage = async () => {
    if (!targetRef.current) return;
    setExporting(true);
    setProgress(30);
    try {
      const canvas = await html2canvas(targetRef.current, { useCORS: true, scale: 2 });
      setProgress(80);
      const link = document.createElement('a');
      link.download = `旅行日记_${new Date().toISOString().slice(0, 10)}.png`;
      link.href = canvas.toDataURL('image/png');
      link.click();
      setProgress(100);
    } catch {
      // handle error
    } finally {
      setExporting(false);
      setProgress(0);
    }
  };

  const handleExportPDF = async () => {
    if (!targetRef.current) return;
    setExporting(true);
    setProgress(30);
    try {
      const canvas = await html2canvas(targetRef.current, { useCORS: true, scale: 2 });
      setProgress(60);
      const imgData = canvas.toDataURL('image/png');
      const pdf = new jsPDF('p', 'mm', 'a4');
      const pdfWidth = pdf.internal.pageSize.getWidth();
      const pdfHeight = (canvas.height * pdfWidth) / canvas.width;
      pdf.addImage(imgData, 'PNG', 0, 0, pdfWidth, pdfHeight);
      pdf.save(`旅行日记_${new Date().toISOString().slice(0, 10)}.pdf`);
      setProgress(100);
    } catch {
      // handle error
    } finally {
      setExporting(false);
      setProgress(0);
    }
  };

  const handleShare = async () => {
    const link = await share();
    if (link) {
      navigator.clipboard.writeText(link);
    }
  };

  return (
    <Modal title="导出与分享" open={visible} onCancel={onClose} footer={null} width={400}>
      <div className={styles.content}>
        {exporting && <Progress percent={progress} status="active" />}
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Button
            icon={<FileImage size={16} />}
            onClick={handleExportImage}
            loading={exporting}
            block
            size="large"
          >
            导出长图
          </Button>
          <Button
            icon={<FileText size={16} />}
            onClick={handleExportPDF}
            loading={exporting}
            block
            size="large"
          >
            导出 PDF
          </Button>
          <Button
            icon={<Share2 size={16} />}
            onClick={handleShare}
            block
            size="large"
          >
            生成分享链接
          </Button>
        </Space>
      </div>
    </Modal>
  );
};

export default ExportModal;
