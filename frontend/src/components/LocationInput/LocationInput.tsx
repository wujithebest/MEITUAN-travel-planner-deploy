import React, { useState } from 'react';
import { Input, Radio, DatePicker, Switch, Button, Space, Tooltip, message } from 'antd';
import { Mic, MicOff, Sparkles, Car, Footprints, Train, Bike } from 'lucide-react';
import dayjs from 'dayjs';
import { useRouteStore } from '@/store/routeStore';
import { useRouteGenerate } from '@/hooks/useRouteGenerate';
import { useSpeechRecognition } from '@/hooks/useSpeechRecognition';
import { validateRouteInput } from '@/utils/validators';
import type { LocationInput as LocationInputType } from '@/api/types';
import styles from './LocationInput.module.css';

const { RangePicker } = DatePicker;
const { TextArea } = Input;

const INTENT_EXAMPLES = [
  '杨浦区工业风两日游',
  '崇明岛生态两日游', 
  '徐汇美食逛街一日游',
];

const TRANSPORT_OPTIONS = [
  { value: 'driving', label: '驾车', icon: Car },
  { value: 'walking', label: '步行', icon: Footprints },
  { value: 'transit', label: '公交', icon: Train },
  { value: 'bicycling', label: '骑行', icon: Bike },
];

const LocationInput: React.FC = () => {
  const [text, setText] = useState('');
  const [dates, setDates] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);
  const transportMode = useRouteStore((s) => s.transportMode);
  const setTransportMode = useRouteStore((s) => s.setTransportMode);
  const considerWeather = useRouteStore((s) => s.considerWeather);
  const setConsiderWeather = useRouteStore((s) => s.setConsiderWeather);
  const loading = useRouteStore((s) => s.loading);
  const error = useRouteStore((s) => s.error);
  const { generate } = useRouteGenerate();
  const { isListening, transcript, isSupported, startListening, stopListening } = useSpeechRecognition();

  const handleGenerate = async () => {
    console.log(`[LocationInput] 点击生成, input=${text}`);
    
    if (!text.trim()) {
      console.warn(`[LocationInput] 输入为空`);
      message.warning('请输入旅行描述');
      return;
    }
    
    if (!dates) {
      console.warn(`[LocationInput] 未选择日期`);
      message.warning('请选择出行日期');
      return;
    }
    
    const days = dates[1].diff(dates[0], 'day') + 1;
    const input: LocationInputType = {
      text,
      plan_mode: 'intent', // 默认设置为意图模式
      transport_mode: transportMode,
      start_date: dates[0].format('YYYY-MM-DD'),
      days,
      consider_weather: considerWeather,
    };
    
    console.log(`[LocationInput] 输入验证, input=`, input);
    const validation = validateRouteInput({
      text: input.text,
      start_date: input.start_date || '',
      days: input.days || 0,
    });
    if (!validation.valid) {
      console.error(`[LocationInput] 验证失败:`, validation.error);
      message.error(validation.error || '输入验证失败');
      return;
    }
    
    try {
      console.log(`[LocationInput] 调用store.generateRoute...`);
      await generate(input);
      console.log(`[LocationInput] generateRoute成功`);
    } catch (err: any) {
      console.error(`[LocationInput] generateRoute失败:`, err);
      message.error(err.message || '生成失败，请检查后端服务');
    }
  };

  const handleSpeechToggle = () => {
    if (isListening) {
      stopListening();
      if (transcript) setText((prev) => prev + transcript);
    } else {
      startListening();
    }
  };

  const handleIntentExampleClick = (example: string) => {
    setText(example);
  };

  return (
    <div className={styles.container}>
      <div className={styles.section}>
        <label className={styles.label}>旅行描述</label>
        <TextArea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="输入具体地点（如人民广场→外滩→豫园）或描述需求（如杨浦区玩两天、崇明岛两日游、徐汇逛街吃美食）"
          rows={4}
          maxLength={500}
          showCount
          className={styles.textarea}
        />
        <div className={styles.examples}>
          {INTENT_EXAMPLES.map((ex, i) => (
            <Button key={i} size="small" type="link" onClick={() => handleIntentExampleClick(ex)}>
              {ex}
            </Button>
          ))}
        </div>
      </div>

      <div className={styles.section}>
        <label className={styles.label}>交通方式</label>
        <Radio.Group value={transportMode} onChange={(e) => setTransportMode(e.target.value)} className={styles.transportGroup}>
          {TRANSPORT_OPTIONS.map((opt) => {
            const Icon = opt.icon;
            return (
              <Radio.Button key={opt.value} value={opt.value} className={styles.transportBtn}>
                <Icon size={16} />
                <span>{opt.label}</span>
              </Radio.Button>
            );
          })}
        </Radio.Group>
      </div>

      <div className={styles.section}>
        <label className={styles.label}>出行日期</label>
        <RangePicker
          value={dates}
          onChange={(d) => setDates(d as [dayjs.Dayjs, dayjs.Dayjs] | null)}
          disabledDate={(current) => current && current < dayjs().startOf('day')}
          format="YYYY-MM-DD"
          className={styles.datePicker}
        />
      </div>

      <div className={styles.section}>
        <Space>
          <label className={styles.label}>天气感知</label>
          <Switch
            checked={considerWeather}
            onChange={setConsiderWeather}
            checkedChildren="开"
            unCheckedChildren="关"
          />
        </Space>
      </div>

      <div className={styles.actions}>
        {isSupported && (
          <Tooltip title={isListening ? '停止录音' : '语音输入'}>
            <Button
              icon={isListening ? <MicOff /> : <Mic />}
              onClick={handleSpeechToggle}
              type={isListening ? 'primary' : 'default'}
              danger={isListening}
              shape="circle"
            />
          </Tooltip>
        )}
        <Button
          type="primary"
          icon={<Sparkles size={16} />}
          onClick={handleGenerate}
          loading={loading}
          disabled={!text || !dates}
          className={styles.generateBtn}
        >
          生成路线
        </Button>
      </div>

      {isListening && (
        <div className={styles.speechHint}>
          🎤 正在录音... {transcript && `"${transcript}"`}
        </div>
      )}
    </div>
  );
};

export default LocationInput;
