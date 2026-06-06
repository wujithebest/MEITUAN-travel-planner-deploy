import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  Form,
  Input,
  Button,
  Steps,
  Select,
  DatePicker,
  Radio,
  message,
  Typography,
  Space,
  Card,
  Row,
  Col,
  Spin,
} from 'antd';
import {
  User,
  Mail,
  Lock,
  Eye,
  EyeOff,
  CheckCircle,
  ArrowLeft,
  ArrowRight,
  Sparkles,
  MapPin,
  Search,
  Navigation,
  Utensils,
  Cake,
  VenetianMask,
} from 'lucide-react';
import dayjs from 'dayjs';
import { useUserStore } from '@/store/userStore';
import { addressApi, DistrictNode, AddressSearchResult } from '@/api/address';
import styles from './RegisterPage.module.css';

const { Title, Text } = Typography;
const { Step } = Steps;

const TRAVEL_PREFERENCES = [
  { id: 'history', label: '历史文化', icon: '🏛️', color: '#8B4513' },
  { id: 'food', label: '美食探店', icon: '🍜', color: '#FF6B35' },
  { id: 'nature', label: '自然风光', icon: '🌳', color: '#4CAF50' },
  { id: 'shopping', label: '购物娱乐', icon: '🛍️', color: '#E91E63' },
  { id: 'art', label: '艺术展览', icon: '🎨', color: '#9C27B0' },
  { id: 'nightlife', label: '夜生活', icon: '🌙', color: '#3F51B5' },
  { id: 'photography', label: '摄影打卡', icon: '📸', color: '#00BCD4' },
  { id: 'family', label: '亲子游玩', icon: '👨‍👩‍👧‍👦', color: '#FF9800' },
  { id: 'adventure', label: '户外探险', icon: '🏔️', color: '#795548' },
];

const TASTE_OPTIONS = [
  { value: '百味皆爱', label: '百味皆爱', icon: '🍽️' },
  { value: '川菜', label: '川菜', icon: '🌶️' },
  { value: '粤菜', label: '粤菜', icon: '🥘' },
  { value: '湘菜', label: '湘菜', icon: '🔥' },
  { value: '鲁菜', label: '鲁菜', icon: '🍲' },
  { value: '苏浙菜', label: '苏浙菜', icon: '🦀' },
  { value: '日料', label: '日料', icon: '🍣' },
  { value: '韩餐', label: '韩餐', icon: '🥩' },
  { value: '西餐', label: '西餐', icon: '🍝' },
  { value: '东南亚菜', label: '东南亚菜', icon: '🍛' },
  { value: '烧烤火锅', label: '烧烤火锅', icon: '🍢' },
  { value: '小吃快餐', label: '小吃快餐', icon: '🥟' },
];

interface RegisterForm {
  username: string;
  email: string;
  password: string;
  confirmPassword: string;
}

const RegisterPage: React.FC = () => {
  const navigate = useNavigate();
  const { register, isLoading, error, clearError } = useUserStore();
  const [currentStep, setCurrentStep] = useState(0);
  const [selectedPrefs, setSelectedPrefs] = useState<string[]>([]);
  const [form] = Form.useForm();
  const [formData, setFormData] = useState<RegisterForm | null>(null);

  // Step 2 state: gender & birthday
  const [gender, setGender] = useState<string | undefined>(undefined);
  const [birthday, setBirthday] = useState<string | undefined>(undefined);
  const [age, setAge] = useState<number | null>(null);

  // Step 4 state: taste preference
  const [tastePreference, setTastePreference] = useState<string>('百味皆爱');

  // Step 5 state: address
  const [provinces, setProvinces] = useState<DistrictNode[]>([]);
  const [cities, setCities] = useState<DistrictNode[]>([]);
  const [districts, setDistricts] = useState<DistrictNode[]>([]);
  const [selectedProvince, setSelectedProvince] = useState<string | undefined>(undefined);
  const [selectedCity, setSelectedCity] = useState<string | undefined>(undefined);
  const [selectedDistrict, setSelectedDistrict] = useState<string | undefined>(undefined);
  const [addressKeyword, setAddressKeyword] = useState('');
  const [addressResults, setAddressResults] = useState<AddressSearchResult[]>([]);
  const [searchingAddress, setSearchingAddress] = useState(false);
  const [selectedAddress, setSelectedAddress] = useState<AddressSearchResult | null>(null);
  const [locating, setLocating] = useState(false);

  const validateEmail = (email: string): boolean => {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
  };

  // Load provinces on mount
  useEffect(() => {
    addressApi.getDistricts('中国', 1).then(setProvinces).catch(() => {});
  }, []);

  // Load cities when province changes
  const handleProvinceChange = useCallback(async (provinceName: string) => {
    setSelectedProvince(provinceName);
    setSelectedCity(undefined);
    setSelectedDistrict(undefined);
    setCities([]);
    setDistricts([]);
    const province = provinces.find((p) => p.name === provinceName);
    if (province?.adcode) {
      try {
        const data = await addressApi.getDistricts(province.adcode, 1);
        setCities(data);
      } catch {
        setCities([]);
      }
    }
  }, [provinces]);

  // Load districts when city changes
  const handleCityChange = useCallback(async (cityName: string) => {
    setSelectedCity(cityName);
    setSelectedDistrict(undefined);
    setDistricts([]);
    const city = cities.find((c) => c.name === cityName);
    if (city?.adcode) {
      try {
        const data = await addressApi.getDistricts(city.adcode, 1);
        setDistricts(data);
      } catch {
        setDistricts([]);
      }
    }
  }, [cities]);

  const handleDistrictChange = useCallback((districtName: string) => {
    setSelectedDistrict(districtName);
  }, []);

  // Gaode address search
  const handleAddressSearch = useCallback(async () => {
    if (!addressKeyword || addressKeyword.length < 2) {
      message.warning('请输入至少2个字符');
      return;
    }
    setSearchingAddress(true);
    try {
      const cityName = selectedCity || selectedProvince || undefined;
      const results = await addressApi.searchAddress(addressKeyword, cityName);
      setAddressResults(results);
      if (results.length === 0) {
        message.info('未找到匹配的地址');
      }
    } catch {
      message.error('地址搜索失败');
    } finally {
      setSearchingAddress(false);
    }
  }, [addressKeyword, selectedCity, selectedProvince]);

  const handleSelectAddress = useCallback((item: AddressSearchResult) => {
    setSelectedAddress(item);
    setAddressKeyword(item.name);
    setAddressResults([]);
  }, []);

  // Geolocation
  const handleGeolocate = useCallback(() => {
    if (!navigator.geolocation) {
      message.error('您的浏览器不支持定位功能');
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        const { longitude, latitude } = position.coords;
        try {
          const result = await addressApi.reverseGeocode(longitude, latitude);
          if (result) {
            setSelectedProvince(result.province);
            setSelectedCity(result.city);
            setSelectedDistrict(result.district);
            setAddressKeyword(result.address);
            setSelectedAddress({
              name: result.address,
              address: result.address,
              location: { lng: result.lng, lat: result.lat },
              district: result.district,
            });
            message.success('定位成功');
          } else {
            message.error('地址解析失败');
          }
        } catch {
          message.error('地址解析失败');
        } finally {
          setLocating(false);
        }
      },
      () => {
        message.error('获取位置失败，请检查定位权限');
        setLocating(false);
      },
      { timeout: 10000, enableHighAccuracy: true }
    );
  }, []);

  // Birthday change → auto-calculate age
  const handleBirthdayChange = useCallback((date: dayjs.Dayjs | null) => {
    if (date) {
      const dateStr = date.format('YYYY-MM-DD');
      setBirthday(dateStr);
      const today = dayjs();
      let calculated = today.year() - date.year();
      if (today.month() < date.month() || (today.month() === date.month() && today.date() < date.date())) {
        calculated--;
      }
      setAge(calculated >= 0 ? calculated : 0);
    } else {
      setBirthday(undefined);
      setAge(null);
    }
  }, []);

  const handleStep1Submit = async (values: RegisterForm) => {
    try {
      clearError();
      if (values.password !== values.confirmPassword) {
        message.error('两次输入的密码不一致');
        return;
      }
      setFormData(values);
      setCurrentStep(1);
    } catch (err: any) {
      console.error('Step 1 failed:', err);
    }
  };

  const handleStep2Next = () => {
    setCurrentStep(2);
  };

  const togglePreference = (prefId: string) => {
    setSelectedPrefs((prev) =>
      prev.includes(prefId) ? prev.filter((p) => p !== prefId) : [...prev, prefId]
    );
  };

  const handleRegister = async () => {
    if (!formData) return;

    const locationData: Record<string, unknown> = {};
    if (selectedProvince) locationData.province = selectedProvince;
    if (selectedCity) locationData.city = selectedCity;
    if (selectedDistrict) locationData.district = selectedDistrict;
    if (selectedAddress) {
      locationData.address = selectedAddress.address;
      if (selectedAddress.location) {
        locationData.latitude = selectedAddress.location.lat;
        locationData.longitude = selectedAddress.location.lng;
      }
    }

    const preferences: Record<string, unknown> = {
      interests: selectedPrefs,
      taste_preference: tastePreference !== '百味皆爱' ? tastePreference : null,
    };

    try {
      await register({
        username: formData.username,
        email: formData.email,
        password: formData.password,
        gender,
        birthday,
        preferences: preferences as unknown as string[],
        location: locationData,
      });
      message.success('注册成功！');
      setCurrentStep(5);
    } catch (err: any) {
      console.error('Registration failed:', err);
    }
  };

  const handleGoHome = () => {
    navigate('/', { replace: true });
  };

  const renderIcon = (visible: boolean) => {
    return visible ? <Eye size={18} /> : <EyeOff size={18} />;
  };

  const steps = [
    { title: '账号信息', icon: <User size={20} /> },
    { title: '个人资料', icon: <VenetianMask size={20} /> },
    { title: '旅行偏好', icon: <Sparkles size={20} /> },
    { title: '口味偏好', icon: <Utensils size={20} /> },
    { title: '地址信息', icon: <MapPin size={20} /> },
    { title: '完成注册', icon: <CheckCircle size={20} /> },
  ];

  return (
    <div className={styles.container}>
      <div className={styles.brandSection}>
        <div className={styles.brandContent}>
          <div className={styles.logo}>🗺️</div>
          <Title level={2} className={styles.brandTitle}>
            加入本地生活路线规划
          </Title>
          <Text className={styles.slogan}>
            开启您的专属本地探索之旅
          </Text>
          <div className={styles.benefits}>
            <div className={styles.benefit}>
              <span className={styles.benefitIcon}>✨</span>
              <span>个性化路线推荐</span>
            </div>
            <div className={styles.benefit}>
              <span className={styles.benefitIcon}>💾</span>
              <span>云端保存旅行记录</span>
            </div>
            <div className={styles.benefit}>
              <span className={styles.benefitIcon}>🤝</span>
              <span>与好友分享行程</span>
            </div>
          </div>
        </div>
      </div>

      <div className={styles.formSection}>
        <div className={styles.formCard}>
          <Steps current={currentStep} className={styles.steps} size="small">
            {steps.map((step, index) => (
              <Step key={index} title={index <= 4 ? step.title : undefined} icon={step.icon} />
            ))}
          </Steps>

          {/* Step 1: Account Info */}
          {currentStep === 0 && (
            <div className={styles.stepContent}>
              <div className={styles.stepHeader}>
                <Title level={3} className={styles.stepTitle}>创建账号</Title>
                <Text className={styles.stepSubtitle}>请填写您的基本信息</Text>
              </div>
              <Form
                form={form}
                layout="vertical"
                onFinish={handleStep1Submit}
                className={styles.form}
                requiredMark={false}
              >
                <Form.Item
                  label="用户名"
                  name="username"
                  rules={[
                    { required: true, message: '请输入用户名' },
                    { min: 2, message: '用户名至少2个字符' },
                    { max: 20, message: '用户名最多20个字符' },
                  ]}
                >
                  <Input
                    prefix={<User size={18} className={styles.inputIcon} />}
                    placeholder="请输入用户名"
                    size="large"
                    className={styles.input}
                  />
                </Form.Item>
                <Form.Item
                  label="邮箱"
                  name="email"
                  rules={[
                    { required: true, message: '请输入邮箱' },
                    {
                      validator: (_, value) => {
                        if (!value || validateEmail(value)) return Promise.resolve();
                        return Promise.reject(new Error('请输入有效的邮箱地址'));
                      },
                    },
                  ]}
                >
                  <Input
                    prefix={<Mail size={18} className={styles.inputIcon} />}
                    placeholder="请输入邮箱地址"
                    size="large"
                    className={styles.input}
                  />
                </Form.Item>
                <Form.Item
                  label="密码"
                  name="password"
                  rules={[{ required: true, message: '请输入密码' }]}
                >
                  <Input.Password
                    prefix={<Lock size={18} className={styles.inputIcon} />}
                    placeholder="请输入密码"
                    size="large"
                    className={styles.input}
                    iconRender={renderIcon}
                  />
                </Form.Item>
                <Form.Item
                  label="确认密码"
                  name="confirmPassword"
                  rules={[
                    { required: true, message: '请再次输入密码' },
                    ({ getFieldValue }) => ({
                      validator(_, value) {
                        if (!value || getFieldValue('password') === value) return Promise.resolve();
                        return Promise.reject(new Error('两次输入的密码不一致'));
                      },
                    }),
                  ]}
                >
                  <Input.Password
                    prefix={<Lock size={18} className={styles.inputIcon} />}
                    placeholder="请再次输入密码"
                    size="large"
                    className={styles.input}
                    iconRender={renderIcon}
                  />
                </Form.Item>
                {error && <div className={styles.errorMessage}>{error}</div>}
                <Form.Item>
                  <Button type="primary" htmlType="submit" size="large" block className={styles.submitBtn}>
                    下一步 <ArrowRight size={18} />
                  </Button>
                </Form.Item>
                <div className={styles.loginLink}>
                  <Text>
                    已有账号？
                    <Link to="/login" className={styles.link}>立即登录</Link>
                  </Text>
                </div>
              </Form>
            </div>
          )}

          {/* Step 2: Personal Info (gender & birthday) */}
          {currentStep === 1 && (
            <div className={styles.stepContent}>
              <div className={styles.stepHeader}>
                <Title level={3} className={styles.stepTitle}>个人资料</Title>
                <Text className={styles.stepSubtitle}>完善您的个人信息，让我们更好地为您服务</Text>
              </div>
              <div className={styles.stepBody}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>
                    <VenetianMask size={16} /> 性别
                  </label>
                  <Select
                    value={gender}
                    onChange={setGender}
                    placeholder="请选择性别"
                    size="large"
                    className={styles.selectField}
                    options={[
                      { value: 'male', label: '男' },
                      { value: 'female', label: '女' },
                    ]}
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>
                    <Cake size={16} /> 生日
                  </label>
                  <DatePicker
                    value={birthday ? dayjs(birthday) : null}
                    onChange={handleBirthdayChange}
                    placeholder="请选择生日"
                    size="large"
                    className={styles.selectField}
                    style={{ width: '100%' }}
                    disabledDate={(d) => d && d.isAfter(dayjs())}
                    format="YYYY-MM-DD"
                  />
                  {age !== null && age >= 0 && (
                    <Text className={styles.ageHint}>当前年龄：{age} 岁</Text>
                  )}
                </div>
              </div>
              <Space className={styles.stepActions} size="large">
                <Button size="large" onClick={() => setCurrentStep(0)} className={styles.backBtn}>
                  <ArrowLeft size={18} /> 上一步
                </Button>
                <Button type="primary" size="large" onClick={handleStep2Next} className={styles.submitBtn}>
                  下一步 <ArrowRight size={18} />
                </Button>
              </Space>
            </div>
          )}

          {/* Step 3: Travel Preferences */}
          {currentStep === 2 && (
            <div className={styles.stepContent}>
              <div className={styles.stepHeader}>
                <Title level={3} className={styles.stepTitle}>选择您的旅行偏好</Title>
                <Text className={styles.stepSubtitle}>选择您感兴趣的旅行类型（可多选）</Text>
              </div>
              <div className={styles.preferences}>
                <Row gutter={[16, 16]}>
                  {TRAVEL_PREFERENCES.map((pref) => (
                    <Col xs={12} sm={8} key={pref.id}>
                      <Card
                        hoverable
                        className={`${styles.prefCard} ${selectedPrefs.includes(pref.id) ? styles.prefCardSelected : ''}`}
                        onClick={() => togglePreference(pref.id)}
                        bodyStyle={{ padding: '16px' }}
                      >
                        <div className={styles.prefContent}>
                          <div className={styles.prefIcon}>{pref.icon}</div>
                          <Text className={styles.prefLabel}>{pref.label}</Text>
                          {selectedPrefs.includes(pref.id) && (
                            <CheckCircle size={20} className={styles.prefCheck} />
                          )}
                        </div>
                      </Card>
                    </Col>
                  ))}
                </Row>
              </div>
              <div className={styles.selectedCount}>
                <Text>已选择 {selectedPrefs.length} 个偏好</Text>
              </div>
              <Space className={styles.stepActions} size="large">
                <Button size="large" onClick={() => setCurrentStep(1)} className={styles.backBtn}>
                  <ArrowLeft size={18} /> 上一步
                </Button>
                <Button type="primary" size="large" onClick={() => setCurrentStep(3)} className={styles.submitBtn}>
                  下一步 <ArrowRight size={18} />
                </Button>
              </Space>
            </div>
          )}

          {/* Step 4: Taste Preference */}
          {currentStep === 3 && (
            <div className={styles.stepContent}>
              <div className={styles.stepHeader}>
                <Title level={3} className={styles.stepTitle}>口味偏好</Title>
                <Text className={styles.stepSubtitle}>选择您最喜欢的菜系口味（单选）</Text>
              </div>
              <div className={styles.tasteGrid}>
                <Radio.Group
                  value={tastePreference}
                  onChange={(e) => setTastePreference(e.target.value)}
                  className={styles.tasteGroup}
                >
                  <Row gutter={[12, 12]}>
                    {TASTE_OPTIONS.map((opt) => (
                      <Col xs={12} sm={8} key={opt.value}>
                        <Radio.Button
                          value={opt.value}
                          className={`${styles.tasteBtn} ${tastePreference === opt.value ? styles.tasteBtnActive : ''}`}
                        >
                          <span className={styles.tasteIcon}>{opt.icon}</span>
                          <span className={styles.tasteLabel}>{opt.label}</span>
                        </Radio.Button>
                      </Col>
                    ))}
                  </Row>
                </Radio.Group>
              </div>
              {tastePreference === '百味皆爱' && (
                <div className={styles.tasteHint}>
                  <Text>选择"百味皆爱"，我们将不限制菜系，为您探索各类美食</Text>
                </div>
              )}
              <Space className={styles.stepActions} size="large">
                <Button size="large" onClick={() => setCurrentStep(2)} className={styles.backBtn}>
                  <ArrowLeft size={18} /> 上一步
                </Button>
                <Button type="primary" size="large" onClick={() => setCurrentStep(4)} className={styles.submitBtn}>
                  下一步 <ArrowRight size={18} />
                </Button>
              </Space>
            </div>
          )}

          {/* Step 5: Address */}
          {currentStep === 4 && (
            <div className={styles.stepContent}>
              <div className={styles.stepHeader}>
                <Title level={3} className={styles.stepTitle}>地址信息</Title>
                <Text className={styles.stepSubtitle}>设置您的常住地址，方便获取周边推荐</Text>
              </div>
              <div className={styles.stepBody}>
                {/* Cascading selectors */}
                <div className={styles.cascadeRow}>
                  <div className={styles.cascadeItem}>
                    <label className={styles.fieldLabel}>省份</label>
                    <Select
                      value={selectedProvince}
                      onChange={(v) => handleProvinceChange(v)}
                      placeholder="选择省份"
                      size="large"
                      showSearch
                      filterOption={(input, option) =>
                        (option?.label as string || '').includes(input)
                      }
                      options={provinces.map((p) => ({ value: p.name, label: p.name }))}
                      className={styles.selectField}
                    />
                  </div>
                  <div className={styles.cascadeItem}>
                    <label className={styles.fieldLabel}>城市</label>
                    <Select
                      value={selectedCity}
                      onChange={(v) => handleCityChange(v)}
                      placeholder="选择城市"
                      size="large"
                      showSearch
                      filterOption={(input, option) =>
                        (option?.label as string || '').includes(input)
                      }
                      options={cities.map((c) => ({ value: c.name, label: c.name }))}
                      className={styles.selectField}
                      disabled={!selectedProvince || cities.length === 0}
                    />
                  </div>
                  <div className={styles.cascadeItem}>
                    <label className={styles.fieldLabel}>区县</label>
                    <Select
                      value={selectedDistrict}
                      onChange={(v) => handleDistrictChange(v)}
                      placeholder="选择区县"
                      size="large"
                      showSearch
                      filterOption={(input, option) =>
                        (option?.label as string || '').includes(input)
                      }
                      options={districts.map((d) => ({ value: d.name, label: d.name }))}
                      className={styles.selectField}
                      disabled={!selectedCity || districts.length === 0}
                    />
                  </div>
                </div>

                {/* Address search */}
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>
                    <Search size={16} /> 搜索详细地址
                  </label>
                  <div className={styles.searchRow}>
                    <Input
                      value={addressKeyword}
                      onChange={(e) => setAddressKeyword(e.target.value)}
                      placeholder="输入小区/写字楼/地标名称搜索"
                      size="large"
                      className={styles.input}
                      onPressEnter={handleAddressSearch}
                    />
                    <Button
                      type="primary"
                      size="large"
                      onClick={handleAddressSearch}
                      loading={searchingAddress}
                      className={styles.searchBtn}
                    >
                      搜索
                    </Button>
                    <Button
                      size="large"
                      onClick={handleGeolocate}
                      loading={locating}
                      icon={<Navigation size={18} />}
                      className={styles.locateBtn}
                    >
                      定位
                    </Button>
                  </div>
                </div>

                {/* Search results */}
                {addressResults.length > 0 && (
                  <div className={styles.addressResults}>
                    {addressResults.map((item, idx) => (
                      <div
                        key={idx}
                        className={styles.addressResultItem}
                        onClick={() => handleSelectAddress(item)}
                      >
                        <MapPin size={14} className={styles.resultIcon} />
                        <div className={styles.resultText}>
                          <Text strong>{item.name}</Text>
                          <Text className={styles.resultAddr}>{item.address}</Text>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Selected address */}
                {selectedAddress && (
                  <div className={styles.selectedAddress}>
                    <CheckCircle size={16} color="#52c41a" />
                    <Text>{selectedAddress.name}</Text>
                    <Text className={styles.resultAddr}>{selectedAddress.address}</Text>
                  </div>
                )}
              </div>
              <Space className={styles.stepActions} size="large">
                <Button size="large" onClick={() => setCurrentStep(3)} className={styles.backBtn}>
                  <ArrowLeft size={18} /> 上一步
                </Button>
                <Button
                  type="primary"
                  size="large"
                  onClick={handleRegister}
                  loading={isLoading}
                  className={styles.submitBtn}
                >
                  {isLoading ? '注册中...' : '完成注册'}
                </Button>
              </Space>
            </div>
          )}

          {/* Step 6: Success */}
          {currentStep === 5 && (
            <div className={styles.stepContent}>
              <div className={styles.successContent}>
                <div className={styles.successIcon}>
                  <CheckCircle size={80} color="#52c41a" />
                </div>
                <Title level={3} className={styles.successTitle}>注册成功！</Title>
                <Text className={styles.successText}>
                  欢迎加入本地生活路线规划
                  <br />
                  开始规划您的精彩旅程吧！
                </Text>
                <Button type="primary" size="large" onClick={handleGoHome} className={styles.submitBtn}>
                  开始探索 <ArrowRight size={18} />
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default RegisterPage;
