import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Modal, Form, Input, Select, Button, message, Divider, AutoComplete, InputNumber, Tooltip } from 'antd';
import { User, MapPin, Heart, Save, Navigation } from 'lucide-react';
import { useUserStore } from '../../store/userStore';
import { userApi } from '../../api/user';
import { FALLBACK_HOME_ADDRESS, FALLBACK_HOME_LOCATION, makeDeviceHomeAddress, makeLocationPayload } from '@/utils/locationDefaults';
import axios from 'axios';
import { buildApiUrl } from '@/config/api.config';
import styles from './SettingsModal.module.css';

// ── 常量 ──

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
  { value: '百味皆爱', label: '百味皆爱' },
  { value: '川菜', label: '川菜' },
  { value: '粤菜', label: '粤菜' },
  { value: '湘菜', label: '湘菜' },
  { value: '鲁菜', label: '鲁菜' },
  { value: '苏浙菜', label: '苏浙菜' },
  { value: '日料', label: '日料' },
  { value: '韩餐', label: '韩餐' },
  { value: '西餐', label: '西餐' },
  { value: '东南亚菜', label: '东南亚菜' },
  { value: '烧烤火锅', label: '烧烤火锅' },
  { value: '小吃快餐', label: '小吃快餐' },
];

// ── 接口 ──

interface AddressOption {
  value: string;
  label: React.ReactNode;
  address: {
    name: string;
    full_address: string;
    lng: number | null;
    lat: number | null;
  };
}

interface HomeAddress {
  name: string;
  full_address: string;
  lng: number | null;
  lat: number | null;
}

interface SettingsModalProps {
  open: boolean;
  onClose: () => void;
  /** v18: 'settings' = 普通设置, 'onboarding' = 首次游客身份定制（不可跳过） */
  mode?: 'settings' | 'onboarding';
  /** v18: 是否允许关闭（onboarding 模式默认 false） */
  closable?: boolean;
  /** v18: 保存成功后的回调 */
  onSaved?: () => void;
}

// ── 辅助函数 ──

const normalizeHomeAddress = (user: any): HomeAddress | null => {
  const homeAddress = user?.location?.home_address;
  if (homeAddress?.name || homeAddress?.full_address) {
    return {
      name: homeAddress.name || homeAddress.full_address || '',
      full_address: homeAddress.full_address || homeAddress.name || '',
      lng: homeAddress.lng ?? null,
      lat: homeAddress.lat ?? null,
    };
  }
  if (user?.home_location?.lat && user?.home_location?.lng) {
    return {
      name: user.home_location.label || '常住地址',
      full_address: user.home_location.label || '常住地址',
      lng: user.home_location.lng,
      lat: user.home_location.lat,
    };
  }
  if (user?.location?.address) {
    return {
      name: user.location.address,
      full_address: user.location.address,
      lng: user.location.longitude ?? null,
      lat: user.location.latitude ?? null,
    };
  }
  return null;
};

// ── 组件 ──

const SettingsModal: React.FC<SettingsModalProps> = ({
  open,
  onClose,
  mode = 'settings',
  closable = true,
  onSaved,
}) => {
  const { user, isGuest, updateUser, updateGuestProfile } = useUserStore();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  // 地址搜索相关状态
  const [addressOptions, setAddressOptions] = useState<AddressOption[]>([]);
  const [searchingAddress, setSearchingAddress] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [selectedAddress, setSelectedAddress] = useState<HomeAddress | null>(null);
  const formRef = useRef(form);
  formRef.current = form;

  // v18: 旅行偏好卡片式选择（onboarding 模式使用，settings 模式也用）
  const [travelPrefs, setTravelPrefs] = useState<string[]>([]);
  const [tastePref, setTastePref] = useState<string>('百味皆爱');

  // v18: 地理定位状态
  const [geoLocated, setGeoLocated] = useState(false);
  const [geoLoading, setGeoLoading] = useState(false);
  const [userEditedAddress, setUserEditedAddress] = useState(false);

  const isOnboarding = mode === 'onboarding';

  // ── 打开时填充表单 ──
  useEffect(() => {
    if (open && user) {
      const normalizedHomeAddress = normalizeHomeAddress(user);
      form.setFieldsValue({
        username: user.username || '',
        email: user.email || '',
        gender: user.gender || '男',
        age: user.age || 30,
        district: user.location?.district || '杨浦区',
        budget_per_capita: user.budget_per_capita || 100,
        food_preferences: user.food_preferences || [],
        preferences: user.preferences || [],
        homeAddress: normalizedHomeAddress?.name || normalizedHomeAddress?.full_address || '',
      });
      setSelectedAddress(normalizedHomeAddress);
      setTravelPrefs(user.preferences || []);
      const fp = (user.food_preferences || [])[0];
      setTastePref(fp && TASTE_OPTIONS.find(o => o.value === fp) ? fp : '百味皆爱');
    } else if (open && !user) {
      form.resetFields();
      setSelectedAddress(null);
      setTravelPrefs([]);
      setTastePref('百味皆爱');
    }
  }, [open, user, form]);

  // v18: onboarding 首次打开自动获取设备位置
  useEffect(() => {
    if (open && isOnboarding && !geoLocated && !userEditedAddress) {
      setGeoLoading(true);
      navigator.geolocation.getCurrentPosition(
        async (position) => {
          const { latitude: lat, longitude: lng } = position.coords;
          try {
            const res = await axios.get(buildApiUrl(`/address/reverse-geocode?lng=${lng}&lat=${lat}`));
            const addr = res.data?.data || res.data;
            const name = addr?.address || addr?.formatted_address || '当前设备位置';
            const homeAddr: HomeAddress = { name, full_address: name, lng, lat };
            setSelectedAddress(homeAddr);
            form.setFieldsValue({ homeAddress: name });
            // 同步写入 store
            const { user: curUser, updateGuestProfile: ugp } = useUserStore.getState();
            if (isGuest && curUser) {
              ugp({
                ...curUser,
                location: {
                  ...curUser.location,
                  home_address: homeAddr,
                  latitude: lat,
                  longitude: lng,
                },
                home_location: makeLocationPayload(lat, lng, name),
              });
            }
          } catch {
            // reverse geocode failed, use raw coords
            const homeAddr = makeDeviceHomeAddress(lat, lng);
            setSelectedAddress(homeAddr);
            form.setFieldsValue({ homeAddress: homeAddr.name });
          }
          setGeoLocated(true);
          setGeoLoading(false);
        },
        () => {
          // geolocation denied or failed, use fallback
          setSelectedAddress(FALLBACK_HOME_ADDRESS);
          form.setFieldsValue({ homeAddress: FALLBACK_HOME_ADDRESS.name });
          setGeoLocated(true);
          setGeoLoading(false);
        },
        { timeout: 8000, enableHighAccuracy: false },
      );
    }
  }, [open, isOnboarding, geoLocated, userEditedAddress, isGuest, form]);

  // 清理定时器
  useEffect(() => {
    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
  }, []);

  // ── 地址搜索 ──
  const doSearch = useCallback(async (keyword: string) => {
    if (!keyword || keyword.length < 2) {
      setAddressOptions([]);
      setDropdownOpen(false);
      return;
    }
    setSearchingAddress(true);
    setDropdownOpen(true);
    try {
      const res = await axios.get(buildApiUrl(`/address/search?keyword=${encodeURIComponent(keyword)}&city=上海`));
      const data = res.data?.data || res.data || [];
      const items = Array.isArray(data) ? data : [];
      const options: AddressOption[] = items.map((item: any) => ({
        value: item.name || item.address || '',
        label: (
          <div className={styles.addressOption}>
            <div className={styles.addressName}>{item.name || item.address}</div>
            <div className={styles.addressDetail}>{item.address || item.district || ''}</div>
          </div>
        ),
        address: {
          name: item.name || item.address || '',
          full_address: item.address || item.name || '',
          lng: item.lng ?? item.location?.lng ?? null,
          lat: item.lat ?? item.location?.lat ?? null,
        },
      }));
      setAddressOptions(options);
      setDropdownOpen(options.length > 0);
    } catch (err) {
      console.error('[SettingsModal] 地址搜索失败:', err);
      setAddressOptions([]);
      setDropdownOpen(false);
    } finally {
      setSearchingAddress(false);
    }
  }, []);

  const handleAddressSearch = useCallback((value: string) => {
    if (!value) return;
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => doSearch(value), 350);
  }, [doSearch]);

  const handleAddressSelect = useCallback((_value: string, option: any) => {
    setSelectedAddress(option.address);
    setUserEditedAddress(true);
  }, []);

  const handleAddressChange = useCallback((value: string) => {
    if (!value) {
      setSelectedAddress(null);
      setAddressOptions([]);
      setDropdownOpen(false);
      setUserEditedAddress(true);
    }
  }, []);

  const handleFocus = useCallback(() => {
    if (addressOptions.length > 0) setDropdownOpen(true);
  }, [addressOptions.length]);

  // v18: 手动定位
  const handleLocate = useCallback(() => {
    setGeoLoading(true);
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        const { latitude: lat, longitude: lng } = position.coords;
        try {
          const res = await axios.get(buildApiUrl(`/address/reverse-geocode?lng=${lng}&lat=${lat}`));
          const addr = res.data?.data || res.data;
          const name = addr?.address || addr?.formatted_address || '当前设备位置';
          const homeAddr: HomeAddress = { name, full_address: name, lng, lat };
          setSelectedAddress(homeAddr);
          form.setFieldsValue({ homeAddress: name });
          setUserEditedAddress(false);
        } catch {
          const homeAddr = makeDeviceHomeAddress(lat, lng);
          setSelectedAddress(homeAddr);
          form.setFieldsValue({ homeAddress: homeAddr.name });
          setUserEditedAddress(false);
        }
        setGeoLoading(false);
      },
      () => {
        message.warning('无法获取设备位置，请手动输入地址');
        setGeoLoading(false);
      },
      { timeout: 8000, enableHighAccuracy: false },
    );
  }, [form]);

  // v18: 旅行偏好切换
  const toggleTravelPref = (id: string) => {
    setTravelPrefs(prev =>
      prev.includes(id) ? prev.filter(p => p !== id) : [...prev, id].slice(0, 5)
    );
  };

  // ── 保存 ──
  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);

      // 合并偏好
      const finalPrefs = isOnboarding ? travelPrefs : (values.preferences || []);
      const finalTaste = isOnboarding
        ? (tastePref !== '百味皆爱' ? [tastePref] : [])
        : (values.food_preferences || []);

      if (isGuest) {
        const updatedLocation = { ...user?.location };
        if (selectedAddress) {
          updatedLocation.home_address = selectedAddress;
        }
        if (values.district) {
          updatedLocation.district = values.district;
        }

        const homeLocation = selectedAddress
          ? {
              lat: selectedAddress.lat ?? FALLBACK_HOME_LOCATION.lat,
              lng: selectedAddress.lng ?? FALLBACK_HOME_LOCATION.lng,
              label: selectedAddress.name || selectedAddress.full_address || FALLBACK_HOME_LOCATION.label,
            }
          : FALLBACK_HOME_LOCATION;

        // v18: 游客模式写入完整字段
        updateGuestProfile({
          username: values.username,
          gender: values.gender,
          age: values.age,
          preferences: finalPrefs,
          activity_pref_tag: finalPrefs,
          food_preferences: finalTaste,
          budget_per_capita: values.budget_per_capita,
          location: {
            ...updatedLocation,
            latitude: selectedAddress?.lat ?? FALLBACK_HOME_LOCATION.lat,
            longitude: selectedAddress?.lng ?? FALLBACK_HOME_LOCATION.lng,
          } as any,
          home_location: homeLocation,
        });

        message.success(isOnboarding ? '身份信息已保存，开始探索吧！' : '设置已保存（本地）');
        setLoading(false);
        onSaved?.();
        onClose();
        return;
      }

      // 注册用户
      const updateData: any = { username: values.username, preferences: finalPrefs };
      if (selectedAddress) {
        updateData.location = { home_address: selectedAddress };
      }
      await userApi.updateProfile(updateData);

      const homeLocation = selectedAddress
        ? {
            lat: selectedAddress.lat || 31.2809,
            lng: selectedAddress.lng || 121.5011,
            label: selectedAddress.name || selectedAddress.full_address || '常住地址',
          }
        : null;

      if (user) {
        updateUser({
          ...user,
          username: values.username,
          preferences: finalPrefs,
          food_preferences: finalTaste,
          location: { ...user.location, home_address: selectedAddress || undefined },
          home_location: homeLocation,
        });
      }

      message.success('设置已保存');
      onSaved?.();
      onClose();
    } catch (error: any) {
      if (error.errorFields) return;
      message.error(error.message || '保存失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  // ── 渲染 ──
  return (
    <Modal
      title={isOnboarding ? '🎉 欢迎！请完善您的出行偏好' : '我的设置'}
      open={open}
      onCancel={closable ? onClose : undefined}
      footer={null}
      width={560}
      centered
      closable={closable}
      maskClosable={closable}
      keyboard={closable}
      className={styles.modal}
    >
      <Form form={form} layout="vertical" className={styles.form}>
        {/* 基本信息 */}
        <div className={styles.section}>
          <div className={styles.sectionHeader}>
            <User size={16} />
            <span>基本信息</span>
          </div>

          <Form.Item
            name="username"
            label="昵称"
            rules={[
              { required: true, message: '请输入昵称' },
              { min: 2, message: '至少2个字符' },
              { max: 20, message: '最多20个字符' },
            ]}
          >
            <Input placeholder="请输入昵称" prefix={<User size={14} color="#999" />} />
          </Form.Item>

          {isGuest && (
            <>
              <div style={{ display: 'flex', gap: 16 }}>
                <Form.Item name="gender" label="性别" style={{ flex: 1 }}>
                  <Select
                    placeholder="选择性别"
                    options={[
                      { value: '男', label: '男' },
                      { value: '女', label: '女' },
                      { value: '其他', label: '其他' },
                    ]}
                  />
                </Form.Item>
                <Form.Item name="age" label="年龄" style={{ flex: 1 }}>
                  <InputNumber min={1} max={120} placeholder="年龄" style={{ width: '100%' }} />
                </Form.Item>
              </div>

              <Form.Item name="district" label="所在区县">
                <Input placeholder="如：杨浦区" />
              </Form.Item>

              <Form.Item name="budget_per_capita" label="人均预算（元）" tooltip="用于筛选餐厅和消费场所">
                <InputNumber
                  min={0} max={10000} step={10}
                  placeholder="人均消费预算"
                  style={{ width: '100%' }}
                  addonAfter="元"
                />
              </Form.Item>
            </>
          )}
        </div>

        <Divider />

        {/* 常驻地址 */}
        <div className={styles.section}>
          <div className={styles.sectionHeader}>
            <MapPin size={16} />
            <span>常驻地址（路线出发地）</span>
          </div>

          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
            <div style={{ flex: 1 }}>
              <Form.Item
                name="homeAddress"
                label=""
                tooltip="输入2个字后开始搜索"
              >
                <AutoComplete
                  placeholder="请输入您的常驻地址（如：陆家嘴、徐家汇）"
                  options={addressOptions}
                  onSelect={handleAddressSelect}
                  onSearch={handleAddressSearch}
                  onChange={(value: any) => {
                    if (!value) { handleAddressChange(''); return; }
                    handleAddressSearch(String(value));
                  }}
                  onFocus={handleFocus}
                  notFoundContent={searchingAddress ? '搜索中...' : '请输入至少2个字进行搜索'}
                  allowClear
                  filterOption={false}
                  open={dropdownOpen}
                  onDropdownVisibleChange={(visible: boolean) => {
                    if (!visible) setDropdownOpen(false);
                    else if (addressOptions.length > 0 || searchingAddress) setDropdownOpen(true);
                  }}
                />
              </Form.Item>
            </div>
            <Tooltip title={geoLoading ? '定位中...' : '获取当前设备位置'}>
              <Button
                icon={<Navigation size={16} />}
                onClick={handleLocate}
                loading={geoLoading}
                style={{ marginTop: 28 }}
              />
            </Tooltip>
          </div>

          {selectedAddress && (
            <div className={styles.selectedAddress}>
              <MapPin size={14} color="#1890ff" />
              <span className={styles.selectedAddressText}>{selectedAddress.full_address}</span>
            </div>
          )}
        </div>

        <Divider />

        {/* 口味偏好 */}
        <div className={styles.section}>
          <div className={styles.sectionHeader}>
            <span>😋</span>
            <span>口味偏好</span>
          </div>
          <Form.Item name="food_preferences" label="选择您喜欢的口味" style={{ marginBottom: 0 }}>
            <Select
              mode="multiple"
              placeholder="选择口味偏好（可多选）"
              options={TASTE_OPTIONS.map(o => ({ value: o.value, label: `${o.label}` }))}
              maxTagCount={6}
            />
          </Form.Item>
        </div>

        <Divider />

        {/* 旅行偏好 — 卡片式 */}
        <div className={styles.section}>
          <div className={styles.sectionHeader}>
            <Heart size={16} />
            <span>旅行偏好（可多选，最多5项）</span>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 16 }}>
            {TRAVEL_PREFERENCES.map(pref => {
              const active = travelPrefs.includes(pref.id);
              return (
                <button
                  key={pref.id}
                  type="button"
                  onClick={() => toggleTravelPref(pref.id)}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 4,
                    padding: '6px 14px', borderRadius: 20, border: `2px solid ${active ? pref.color : '#e8e8e8'}`,
                    background: active ? `${pref.color}15` : '#fff',
                    cursor: 'pointer', fontSize: 13, fontWeight: active ? 600 : 400,
                    color: active ? pref.color : '#666',
                    transition: 'all 0.2s', outline: 'none',
                  }}
                >
                  <span>{pref.icon}</span>
                  <span>{pref.label}</span>
                </button>
              );
            })}
          </div>
          {/* 隐藏的 Form.Item 用于兼容 settings 模式的 preferences Select */}
          {!isOnboarding && (
            <Form.Item name="preferences" style={{ display: 'none' }}>
              <Select mode="multiple" />
            </Form.Item>
          )}
        </div>

        {/* 提交按钮 */}
        <div className={styles.actions}>
          {closable && <Button onClick={onClose}>取消</Button>}
          <Button
            type="primary"
            icon={<Save size={14} />}
            onClick={handleSubmit}
            loading={loading}
            className={styles.submitBtn}
          >
            {isOnboarding ? '开始探索' : '保存设置'}
          </Button>
        </div>
      </Form>
    </Modal>
  );
};

export default SettingsModal;
