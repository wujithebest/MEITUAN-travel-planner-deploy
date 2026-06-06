import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { 
  Form, 
  Input, 
  Button, 
  Checkbox, 
  Divider, 
  message,
  Typography 
} from 'antd';
import { 
  MailOutlined, 
  LockOutlined, 
  EyeOutlined, 
  EyeInvisibleOutlined,
  WechatOutlined,
  QqOutlined
} from '@ant-design/icons';
import { useUserStore } from '@/store/userStore';
import styles from './LoginPage.module.css';

const { Title, Text } = Typography;

interface LoginForm {
  email: string;
  password: string;
  remember: boolean;
}

const LoginPage: React.FC = () => {
  const navigate = useNavigate();
  const { login, isLoading, error, clearError } = useUserStore();
  const [form] = Form.useForm();
  const [passwordVisible, setPasswordVisible] = useState(false);

  // 邮箱验证规则
  const validateEmail = (email: string): boolean => {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
  };

  // 处理登录
  const handleLogin = async (values: LoginForm) => {
    try {
      clearError();
      
      // 前端验证
      if (!validateEmail(values.email)) {
        message.error('请输入有效的邮箱地址');
        return;
      }

      if (values.password.length < 6) {
        message.error('密码至少需要6个字符');
        return;
      }

      await login(values.email, values.password);
      message.success('登录成功！');
      navigate('/', { replace: true });
    } catch (err: any) {
      // 错误已在 store 中处理
      console.error('Login failed:', err);
    }
  };

  return (
    <div className={styles.container}>
      {/* 左侧品牌区域 */}
      <div className={styles.brandSection}>
        <div className={styles.brandContent}>
          {/* 本地地标插画 */}
          <div className={styles.illustration}>
            <svg viewBox="0 0 400 300" className={styles.citySvg}>
              {/* 天空背景 */}
              <defs>
                <linearGradient id="skyGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                  <stop offset="0%" stopColor="#87CEEB" />
                  <stop offset="100%" stopColor="#E0F6FF" />
                </linearGradient>
              </defs>
              <rect width="400" height="300" fill="url(#skyGradient)" />
              
              {/* 东方明珠 */}
              <g transform="translate(200, 100)">
                <rect x="-5" y="0" width="10" height="80" fill="#C0C0C0" />
                <circle cx="0" cy="-10" r="25" fill="#FF6B6B" />
                <circle cx="0" cy="20" r="15" fill="#4ECDC4" />
                <rect x="-3" y="50" width="6" height="30" fill="#C0C0C0" />
              </g>
              
              {/* 本地中心大厦 */}
              <g transform="translate(280, 80)">
                <polygon points="0,120 -25,120 0,0 25,120" fill="#4A90D9" />
                <rect x="-20" y="120" width="40" height="10" fill="#3A7BC8" />
              </g>
              
              {/* 金茂大厦 */}
              <g transform="translate(120, 100)">
                <polygon points="0,100 -20,100 0,10 20,100" fill="#5D9B8C" />
                <rect x="-15" y="100" width="30" height="10" fill="#4A8B7C" />
              </g>
              
              {/* 环球金融中心 */}
              <g transform="translate(240, 110)">
                <rect x="-15" y="0" width="30" height="90" fill="#6B8E9F" />
                <polygon points="0,-20 -10,0 10,0" fill="#5A7D8E" />
                <rect x="-15" y="90" width="30" height="10" fill="#5A7D8E" />
              </g>
              
              {/* 外滩建筑群 */}
              <g transform="translate(50, 180)">
                <rect x="0" y="20" width="30" height="60" fill="#D4A574" />
                <rect x="35" y="30" width="25" height="50" fill="#C4956A" />
                <rect x="65" y="15" width="35" height="65" fill="#B8895E" />
                <rect x="105" y="25" width="28" height="55" fill="#D4A574" />
                <rect x="138" y="35" width="22" height="45" fill="#C4956A" />
              </g>
              
              {/* 黄浦江 */}
              <rect x="0" y="260" width="400" height="40" fill="#87CEEB" opacity="0.5" />
              
              {/* 云朵 */}
              <g fill="white" opacity="0.8">
                <ellipse cx="80" cy="40" rx="30" ry="15" />
                <ellipse cx="100" cy="35" rx="25" ry="12" />
                <ellipse cx="320" cy="50" rx="35" ry="18" />
                <ellipse cx="345" cy="45" rx="28" ry="14" />
              </g>
            </svg>
          </div>
          
          <Title level={2} className={styles.brandTitle}>
            本地生活路线规划
          </Title>
          <Text className={styles.slogan}>
            发现本地，规划你的城市之旅
          </Text>
          <div className={styles.features}>
            <div className={styles.feature}>
              <span className={styles.featureIcon}>🗺️</span>
              <span>智能路线规划</span>
            </div>
            <div className={styles.feature}>
              <span className={styles.featureIcon}>📍</span>
              <span>热门景点推荐</span>
            </div>
            <div className={styles.feature}>
              <span className={styles.featureIcon}>📝</span>
              <span>旅行日记记录</span>
            </div>
          </div>
        </div>
      </div>

      {/* 右侧登录表单 */}
      <div className={styles.formSection}>
        <div className={styles.formCard}>
          <div className={styles.formHeader}>
            <Title level={3} className={styles.formTitle}>
              欢迎回来
            </Title>
            <Text className={styles.formSubtitle}>
              登录您的账号继续使用
            </Text>
          </div>

          <Form
            form={form}
            layout="vertical"
            onFinish={handleLogin}
            className={styles.form}
            requiredMark={false}
          >
            <Form.Item
              label="邮箱"
              name="email"
              rules={[
                { required: true, message: '请输入邮箱' },
                { 
                  validator: (_, value) => {
                    if (!value || validateEmail(value)) {
                      return Promise.resolve();
                    }
                    return Promise.reject(new Error('请输入有效的邮箱地址'));
                  }
                }
              ]}
            >
              <Input
                prefix={<MailOutlined style={{ color: '#bfbfbf', fontSize: 18 }} />}
                placeholder="请输入邮箱地址"
                size="large"
                className={styles.input}
              />
            </Form.Item>

            <Form.Item
              label="密码"
              name="password"
              rules={[
                { required: true, message: '请输入密码' },
                { min: 6, message: '密码至少需要6个字符' }
              ]}
            >
              <Input.Password
                prefix={<LockOutlined style={{ color: '#bfbfbf', fontSize: 18 }} />}
                placeholder="请输入密码"
                size="large"
                className={styles.input}
                visibilityToggle={{
                  visible: passwordVisible,
                  onVisibleChange: setPasswordVisible,
                }}
                iconRender={(visible) => visible ? <EyeOutlined style={{ fontSize: 18 }} /> : <EyeInvisibleOutlined style={{ fontSize: 18 }} />}
              />
            </Form.Item>

            <div className={styles.formOptions}>
              <Form.Item name="remember" valuePropName="checked" noStyle>
                <Checkbox className={styles.rememberCheckbox}>
                  记住我
                </Checkbox>
              </Form.Item>
              <Link to="/forgot-password" className={styles.forgotLink}>
                忘记密码？
              </Link>
            </div>

            {error && (
              <div className={styles.errorMessage}>
                {error}
              </div>
            )}

            <Form.Item>
              <Button
                type="primary"
                htmlType="submit"
                size="large"
                block
                loading={isLoading}
                className={styles.submitBtn}
              >
                {isLoading ? '登录中...' : '登录'}
              </Button>
            </Form.Item>

            <Divider className={styles.divider}>
              <Text className={styles.dividerText}>或使用第三方登录</Text>
            </Divider>

            <div className={styles.socialLogin}>
              <Button
                className={`${styles.socialBtn} ${styles.wechatBtn}`}
                disabled
                title="微信登录（即将推出）"
              >
                <WechatOutlined style={{ fontSize: 20 }} />
                <span>微信</span>
              </Button>
              <Button
                className={`${styles.socialBtn} ${styles.qqBtn}`}
                disabled
                title="QQ登录（即将推出）"
              >
                <QqOutlined style={{ fontSize: 20 }} />
                <span>QQ</span>
              </Button>
            </div>

            <div className={styles.registerLink}>
              <Text>
                还没有账号？
                <Link to="/register" className={styles.link}>
                  立即注册
                </Link>
              </Text>
            </div>
          </Form>
        </div>
      </div>
    </div>
  );
};

export default LoginPage;
