import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Modal, Form, Input, Select, Button, message, Divider, AutoComplete, InputNumber, Tooltip } from 'antd';
import { User, MapPin, Heart, Save, Navigation, ChefHat } from 'lucide-react';
import { useUserStore } from '../../store/userStore';
import { userApi } from '../../api/user';
import { FALLBACK_HOME_ADDRESS, FALLBACK_HOME_LOCATION, makeDeviceHomeAddress, makeLocationPayload } from '@/utils/locationDefaults';
import axios from 'axios';
import { buildApiUrl } from '@/config/api.config';
import styles from './SettingsModal.module.css';

// ── 常量 ──

const MAX_ACTIVITY_PREFS = 3;

/** 路线出发地支持的搜索城市 */
const SUPPORTED_DEPARTURE_CITIES = ['上海', '北京'] as const;

const ACTIVITY_PREFERENCES = [
  { id: 'history', label: '历史文化', tag: '历史文化', icon: '🏛️', color: '#8B4513' },
  { id: 'food', label: '美食探店', tag: '美食', icon: '🍜', color: '#FF6B35' },
  { id: 'nature', label: '自然风光', tag: '自然风光', icon: '🌳', color: '#4CAF50' },
  { id: 'shopping', label: '购物娱乐', tag: '购物娱乐', icon: '🛍️', color: '#E91E63' },
  { id: 'art', label: '艺术展览', tag: '文艺', icon: '🎨', color: '#9C27B0' },
  { id: 'nightlife', label: '夜生活', tag: '夜生活', icon: '🌙', color: '#3F51B5' },
  { id: 'photography', label: '摄影打卡', tag: '拍照', icon: '📸', color: '#00BCD4' },
  { id: 'family', label: '亲子游玩', tag: '亲子', icon: '👨‍👩‍👧‍👦', color: '#FF9800' },
  { id: 'adventure', label: '户外探险', tag: '户外', icon: '🏔️', color: '#795548' },
  { id: 'citywalk', label: '城市漫游', tag: '城市漫游', icon: '🚶', color: '#0EA5E9' },
  { id: 'local', label: '在地市井', tag: '本地特色', icon: '🏮', color: '#D97706' },
  { id: 'wellness', label: '康养疗愈', tag: '康养疗愈', icon: '🧘', color: '#10B981' },
];

const TASTE_OPTIONS = [
  { value: '百味皆爱', label: '百味皆爱', color: '#8B4513' },
  { value: '川菜', label: '川菜', color: '#DC2626' },
  { value: '粤菜', label: '粤菜', color: '#D97706' },
  { value: '湘菜', label: '湘菜', color: '#EA580C' },
  { value: '鲁菜', label: '鲁菜', color: '#CA8A04' },
  { value: '苏浙菜', label: '苏浙菜', color: '#059669' },
  { value: '日料', label: '日料', color: '#7C3AED' },
  { value: '韩餐', label: '韩餐', color: '#DB2777' },
  { value: '西餐', label: '西餐', color: '#2563EB' },
  { value: '东南亚菜', label: '东南亚菜', color: '#0891B2' },
  { value: '烧烤火锅', label: '烧烤火锅', color: '#E11D48' },
  { value: '小吃快餐', label: '小吃快餐', color: '#F59E0B' },
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
  mode?: 'settings' | 'onboarding';
  closable?: boolean;
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

  // 旅行偏好 & 口味偏好（统一用 chip 状态，不依赖 Form 字段）
  const [travelPrefs, setTravelPrefs] = useState<string[]>([]);
  const [tastePref, setTastePref] = useState<string>('百味皆爱');

  // 地理定位状态
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
        gender: user.gender || '男',
        age: user.age || 30,
        budget_per_capita: user.budget_per_capita || 100,
        homeAddress: normalizedHomeAddress?.name || normalizedHomeAddress?.full_address || '',
      });
      setSelectedAddress(normalizedHomeAddress);
      // v18: 回显时兼容旧数据 — 优先 id，其次从 activity_pref_tag 中文反查
      const rawPrefs = (user.preferences || []).filter((p: string) =>
        ACTIVITY_PREFERENCES.some(ap => ap.id === p)
      );
      if (rawPrefs.length > 0) {
        setTravelPrefs(rawPrefs.slice(0, MAX_ACTIVITY_PREFS));
      } else if ((user.activity_pref_tag || []).length > 0) {
        const mapped = (user.activity_pref_tag || [])
          .map((tag: string) => ACTIVITY_PREFERENCES.find(ap => ap.tag === tag)?.id)
          .filter(Boolean) as string[];
        setTravelPrefs(mapped.slice(0, MAX_ACTIVITY_PREFS));
      } else {
        setTravelPrefs([]);
      }
      const fp = (user.food_preferences || [])[0];
      setTastePref(fp && TASTE_OPTIONS.find(o => o.value === fp) ? fp : '百味皆爱');
    } else if (open && !user) {
      form.resetFields();
      setSelectedAddress(null);
      setTravelPrefs([]);
      setTastePref('百味皆爱');
    }
  }, [open, user, form]);

  // ── onboarding 首次打开自动获取设备位置 ──
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
            const homeAddr = makeDeviceHomeAddress(lat, lng);
            setSelectedAddress(homeAddr);
            form.setFieldsValue({ homeAddress: homeAddr.name });
          }
          setGeoLocated(true);
          setGeoLoading(false);
        },
        () => {
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

  // ── 地址搜索（上海 + 北京双城并发，Promise.allSettled 防单城失败）──
  const doSearch = useCallback(async (keyword: string) => {
    if (!keyword || keyword.length < 2) {
      setAddressOptions([]);
      setDropdownOpen(false);
      return;
    }
    setSearchingAddress(true);
    setDropdownOpen(true);
    try {
      const results = await Promise.allSettled(
        SUPPORTED_DEPARTURE_CITIES.map(city =>
          axios.get(buildApiUrl(`/address/search?keyword=${encodeURIComponent(keyword)}&city=${encodeURIComponent(city)}`))
        )
      );

      // 合并两个城市的结果，标记来源城市
      const allItems: (Record<string, any> & { _city: string })[] = [];
      results.forEach((result, i) => {
        if (result.status === 'fulfilled') {
          const data = result.value.data?.data || result.value.data || [];
          const items = Array.isArray(data) ? data : [];
          const city = SUPPORTED_DEPARTURE_CITIES[i];
          items.forEach((item: any) => {
            allItems.push({ ...item, _city: city });
          });
        }
      });

      // 按「名称 + 经纬度」去重
      const seen = new Set<string>();
      const uniqueItems = allItems.filter(item => {
        const key = [
          item.name || item.address || '',
          item.lng ?? item.location?.lng ?? '',
          item.lat ?? item.location?.lat ?? '',
        ].join('|');
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });

      const options: AddressOption[] = uniqueItems.map((item: any) => {
        const city = item._city;
        const district = item.district || '';
        const poiName = item.name || item.address || '';
        const cityDistrict = [city, district].filter(Boolean).join(' · ');
        return {
          value: poiName,
          label: (
            <div className={styles.addressOption}>
              <div className={styles.addressName}>
                {city} · {district} · {poiName}
              </div>
              <div className={styles.addressDetail}>{item.address || item.district || ''}</div>
            </div>
          ),
          address: {
            name: poiName,
            full_address: `${cityDistrict} · ${poiName}`,
            lng: item.lng ?? item.location?.lng ?? null,
            lat: item.lat ?? item.location?.lat ?? null,
          },
        };
      });
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

  // 手动定位
  const handleLocate = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
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

  // ── 偏好切换 ──
  const toggleTravelPref = (id: string) => {
    setTravelPrefs(prev => {
      if (prev.includes(id)) return prev.filter(p => p !== id);
      if (prev.length >= MAX_ACTIVITY_PREFS) {
        message.warning(`活动偏好最多选择${MAX_ACTIVITY_PREFS}项`);
        return prev;
      }
      return [...prev, id];
    });
  };

  const toggleTastePref = (value: string) => {
    setTastePref(prev => (prev === value ? '百味皆爱' : value));
  };

  // ── 保存 ──
  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);

      // v18: 拆分为 UI id 和后端中文 tag
      const finalPrefs = travelPrefs.slice(0, MAX_ACTIVITY_PREFS);
      const finalActivityTags = finalPrefs
        .map(id => ACTIVITY_PREFERENCES.find(pref => pref.id === id)?.tag)
        .filter(Boolean) as string[];
      const finalTaste = tastePref && tastePref !== '百味皆爱' ? [tastePref] : [];

      if (isGuest) {
        const updatedLocation = { ...user?.location };
        if (selectedAddress) {
          updatedLocation.home_address = selectedAddress;
        }

        const homeLocation = selectedAddress
          ? {
              lat: selectedAddress.lat ?? FALLBACK_HOME_LOCATION.lat,
              lng: selectedAddress.lng ?? FALLBACK_HOME_LOCATION.lng,
              label: selectedAddress.name || selectedAddress.full_address || FALLBACK_HOME_LOCATION.label,
            }
          : FALLBACK_HOME_LOCATION;

        updateGuestProfile({
          username: values.username,
          gender: values.gender,
          age: values.age,
          preferences: finalPrefs,
          activity_pref_tag: finalActivityTags,
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
          activity_pref_tag: finalActivityTags,
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
      width={680}
      centered
      closable={closable}
      maskClosable={closable}
      keyboard={closable}
      className={styles.modal}
    >
      <Form form={form} layout="vertical" className={styles.form}>
        {/* ── 滚动区域 ── */}
        <div className={styles.scrollBody}>
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
                <div className={styles.inlineRow}>
                  <Form.Item name="gender" label="性别" className={styles.inlineItem}>
                    <Select
                      placeholder="选择性别"
                      options={[
                        { value: '男', label: '男' },
                        { value: '女', label: '女' },
                        { value: '其他', label: '其他' },
                      ]}
                    />
                  </Form.Item>
                  <Form.Item name="age" label="年龄" className={styles.inlineItem}>
                    <InputNumber min={1} max={120} placeholder="年龄" style={{ width: '100%' }} />
                  </Form.Item>
                </div>

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
              <span>路线出发地</span>
            </div>
            <p className={styles.sectionHint}>可定位获取设备位置 或 手动搜索选择地址</p>

            <div className={styles.addressInputWrap}>
              <Form.Item
                name="homeAddress"
                label=""
                tooltip="输入2个字后开始搜索"
                style={{ marginBottom: 0 }}
              >
                <AutoComplete
                  className={styles.addressAutoComplete}
                  placeholder="请输入路线出发地（如：上海陆家嘴、北京国贸）"
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
              <Tooltip
                title={
                  <span className={styles.locateTooltipText}>
                    {geoLoading ? '定位中...' : '获取当前设备位置'}
                  </span>
                }
              >
                <button
                  type="button"
                  className={styles.locateIconButton}
                  onClick={handleLocate}
                  disabled={geoLoading}
                >
                  <Navigation size={18} />
                </button>
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

          {/* 口味偏好 — chip 单选 */}
          <div className={styles.section}>
            <div className={styles.sectionHeader}>
              <ChefHat size={16} />
              <span>口味偏好</span>
            </div>
            <p className={styles.sectionHint}>选择您喜欢的口味（单选，可取消）</p>
            <div className={styles.chipGrid}>
              {TASTE_OPTIONS.map(opt => {
                const active = tastePref === opt.value;
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => toggleTastePref(opt.value)}
                    className={`${styles.choiceChip} ${active ? styles.choiceChipActive : ''}`}
                    style={{
                      ['--chip-color' as any]: opt.color,
                      ['--chip-bg' as any]: `${opt.color}15`,
                    }}
                  >
                    {opt.label}
                    {active && <span className={styles.choiceChipX}>×</span>}
                  </button>
                );
              })}
            </div>
          </div>

          <Divider />

          {/* 活动偏好 — chip 多选 */}
          <div className={styles.section}>
            <div className={styles.sectionHeader}>
              <Heart size={16} />
              <span>活动偏好（可多选，最多3项）</span>
            </div>
            <div className={styles.chipGrid}>
              {ACTIVITY_PREFERENCES.map(pref => {
                const active = travelPrefs.includes(pref.id);
                return (
                  <button
                    key={pref.id}
                    type="button"
                    onClick={() => toggleTravelPref(pref.id)}
                    className={`${styles.choiceChip} ${active ? styles.choiceChipActive : ''}`}
                    style={{
                      ['--chip-color' as any]: pref.color,
                      ['--chip-bg' as any]: `${pref.color}15`,
                    }}
                  >
                    <span>{pref.icon}</span>
                    <span>{pref.label}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* ── 固定在底部的操作按钮 ── */}
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
