import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Modal, Form, Input, Button, message, Divider, AutoComplete, InputNumber } from 'antd';
import { User, MapPin, Heart, Save } from 'lucide-react';
import { useUserStore } from '../../store/userStore';
import { userApi } from '../../api/user';
import { FALLBACK_HOME_ADDRESS, FALLBACK_HOME_LOCATION, makeDeviceHomeAddress, makeLocationPayload } from '@/utils/locationDefaults';
import axios from 'axios';
import { buildApiUrl } from '@/config/api.config';
import styles from './SettingsModal.module.css';

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
}

const preferenceOptions = [
  { value: 'scenic', label: '自然风光' },
  { value: 'cultural', label: '人文古迹' },
  { value: 'food', label: '美食探店' },
  { value: 'shopping', label: '购物休闲' },
  { value: 'adventure', label: '户外探险' },
  { value: 'relax', label: '休闲度假' },
  { value: 'photography', label: '摄影打卡' },
  { value: 'family', label: '亲子游玩' },
];

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

const SettingsModal: React.FC<SettingsModalProps> = ({ open, onClose }) => {
  const { user, isGuest, updateUser, updateGuestProfile } = useUserStore();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  
  // 地址搜索相关状态
  const [addressOptions, setAddressOptions] = useState<AddressOption[]>([]);
  const [searchingAddress, setSearchingAddress] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [selectedAddress, setSelectedAddress] = useState<HomeAddress | null>(null);
  // 用 ref 保存 form 引用，避免 useCallback 依赖 form 导致防抖重建
  const formRef = useRef(form);
  formRef.current = form;

  useEffect(() => {
    if (open && user) {
      const normalizedHomeAddress = normalizeHomeAddress(user);
      form.setFieldsValue({
        username: user.username || '',
        email: user.email || '',
        preferences: user.preferences || [],
        homeAddress: normalizedHomeAddress?.name || normalizedHomeAddress?.full_address || '',
      });
      if (isGuest) {
        form.setFieldsValue({
          gender: user.gender || '男',
          age: user.age || 30,
          district: user.location?.district || '杨浦区',
          budget_per_capita: user.budget_per_capita || 100,
          food_preferences: user.food_preferences || [],
        });
      }
      setSelectedAddress(normalizedHomeAddress);
    } else if (open && !user) {
      form.resetFields();
      setSelectedAddress(null);
    }
  }, [open, user, form, isGuest]);

  // 组件卸载时清理定时器
  useEffect(() => {
    return () => {
      if (debounceTimer.current) {
        clearTimeout(debounceTimer.current);
      }
    };
  }, []);

  // 游客模式首次打开时尝试获取设备位置
  const [geoLocated, setGeoLocated] = useState(false);
  useEffect(() => {
    if (open && isGuest && !geoLocated && navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          const { latitude, longitude, accuracy } = position.coords;
          console.log('[SettingsModal] 设备定位成功:', { latitude, longitude });
          if (accuracy && accuracy > 300) {
            console.warn(`[LocationDebug] SettingsModal geolocation accuracy is low: ${accuracy}m`);
          }
          const hasManualHome = !!user?.location?.home_address || !!user?.home_location;
          // 用户手动修改过常住地址后，不再被自动定位覆盖
          const homeAddress = hasManualHome ? user?.location?.home_address : makeDeviceHomeAddress(latitude, longitude);
          const homeLocation = hasManualHome ? user?.home_location : makeLocationPayload(latitude, longitude);
          updateGuestProfile({
            location: {
              ...user?.location,
              latitude,
              longitude,
              home_address: homeAddress,
            },
            home_location: homeLocation,
          });
          setGeoLocated(true);
        },
        (err) => {
          console.warn('[SettingsModal] 设备定位失败，使用默认位置:', err.message);
          if (!user?.location?.home_address && !user?.home_location) {
            updateGuestProfile({
              location: {
                ...user?.location,
                latitude: FALLBACK_HOME_LOCATION.lat,
                longitude: FALLBACK_HOME_LOCATION.lng,
                home_address: FALLBACK_HOME_ADDRESS,
              },
              home_location: FALLBACK_HOME_LOCATION,
            });
          }
          setGeoLocated(true);
        },
        { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 }
      );
    }
  }, [open, isGuest, geoLocated, user?.location, user?.home_location, updateGuestProfile]);

  // 地址搜索函数（带防抖）- 不依赖 form，使用 formRef
  const doSearch = useCallback(async (keyword: string) => {
    // 关键词少于2个字符时不搜索
    if (!keyword || keyword.length < 2) {
      setAddressOptions([]);
      setDropdownOpen(false);
      return;
    }

    setSearchingAddress(true);
    setDropdownOpen(true);

    try {
      // 地址搜索城市固定为上海
      const params = new URLSearchParams({ keyword });
      params.append('city', '上海');
      
      // 使用相对路径，通过 Vite 代理转发到后端
      // 注意：不使用 baseURL: ''，直接用相对路径让 axios 使用默认 baseURL（空字符串）
      // Vite 代理会将 /api/* 请求转发到 http://localhost:8002
      const response = await axios.get(buildApiUrl(`/address/search?${params.toString()}`));
      
      console.log('[AddressSearch] API响应:', response.data);
      
      const data = response.data?.data || [];
      
      // 格式化选项
      const options: AddressOption[] = data.map((item: any) => ({
        value: item.name,
        label: (
          <div className={styles.addressOption}>
            <div className={styles.addressName}>{item.name}</div>
            <div className={styles.addressDetail}>
              {item.district && <span>{item.district} </span>}
              {item.address}
            </div>
          </div>
        ),
        address: {
          name: item.name,
          full_address: item.address,
          lng: item.location?.lng || null,
          lat: item.location?.lat || null,
        },
      }));
      
      console.log('[AddressSearch] 格式化后的选项数:', options.length);
      setAddressOptions(options);
      // 有结果时保持下拉打开，无结果时也打开以显示 notFoundContent
      setDropdownOpen(options.length > 0 || response.data?.status === 'success');
    } catch (error: any) {
      console.error('[AddressSearch] 地址搜索失败:', error);
      // 显示网络错误信息
      setAddressOptions([]);
      setDropdownOpen(false);
    } finally {
      setSearchingAddress(false);
    }
  }, []);

  // 防抖搜索入口
  const handleAddressSearch = useCallback((keyword: string) => {
    // 清除之前的定时器
    if (debounceTimer.current) {
      clearTimeout(debounceTimer.current);
    }

    // 关键词少于2个字符时立即清空
    if (!keyword || keyword.length < 2) {
      setAddressOptions([]);
      setDropdownOpen(false);
      return;
    }

    // 设置防抖定时器（350ms，留余量避免中文输入法问题）
    debounceTimer.current = setTimeout(() => {
      doSearch(keyword);
    }, 350);
  }, [doSearch]);

  // 地址选择处理
  const handleAddressSelect = useCallback((value: string, option: any) => {
    console.log('[AddressSearch] 选中地址:', option?.address);
    if (option?.address) {
      setSelectedAddress(option.address);
    }
  }, []);

  // 地址输入变化处理
  const handleAddressChange = useCallback((value: string) => {
    if (!value) {
      setSelectedAddress(null);
      setAddressOptions([]);
      setDropdownOpen(false);
    }
  }, []);

  // 输入框获得焦点时，如果有已保存的地址或有选项，显示下拉
  const handleFocus = useCallback(() => {
    if (addressOptions.length > 0) {
      setDropdownOpen(true);
    }
  }, [addressOptions.length]);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);

      if (isGuest) {
        // 游客模式：本地保存
        const updatedLocation = { ...user?.location };
        if (selectedAddress) {
          updatedLocation.home_address = selectedAddress;
        }
        if (values.district) {
          updatedLocation.district = values.district;
        }

        // v6: 同时写入 home_location（用于路线规划）
        const homeLocation = selectedAddress
          ? {
              lat: selectedAddress.lat ?? FALLBACK_HOME_LOCATION.lat,
              lng: selectedAddress.lng ?? FALLBACK_HOME_LOCATION.lng,
              label: selectedAddress.name || selectedAddress.full_address || FALLBACK_HOME_LOCATION.label,
            }
          : null;

        updateGuestProfile({
          username: values.username,
          gender: values.gender,
          age: values.age,
          preferences: values.preferences,
          food_preferences: values.food_preferences,
          budget_per_capita: values.budget_per_capita,
          location: updatedLocation as any,
          home_location: homeLocation,
        });

        message.success('设置已保存（本地）');
        setLoading(false);
        onClose();
        return;
      }

      // 注册用户：调用 API
      const updateData: any = {
        username: values.username,
        preferences: values.preferences,
      };

      if (selectedAddress) {
        updateData.location = {
          home_address: selectedAddress,
        };
      }

      await userApi.updateProfile(updateData);

      // v6: 构建 home_location
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
          preferences: values.preferences,
          location: {
            ...user.location,
            home_address: selectedAddress || undefined,
          },
          home_location: homeLocation,
        });
      }

      message.success('设置已保存');
      onClose();
    } catch (error: any) {
      if (error.errorFields) {
        return;
      }
      message.error(error.message || '保存失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title="我的设置"
      open={open}
      onCancel={onClose}
      footer={null}
      width={520}
      centered
      className={styles.modal}
    >
      <Form
        form={form}
        layout="vertical"
        className={styles.form}
      >
        {/* 基本信息 */}
        <div className={styles.section}>
          <div className={styles.sectionHeader}>
            <User size={16} />
            <span>基本信息</span>
          </div>
          
          <Form.Item
            name="username"
            label="用户名"
            rules={[
              { required: true, message: '请输入用户名' },
              { min: 2, message: '用户名至少2个字符' },
              { max: 20, message: '用户名最多20个字符' },
            ]}
          >
            <Input
              placeholder="请输入用户名"
              prefix={<User size={14} color="#999" />}
            />
          </Form.Item>

          <Form.Item
            name="email"
            label="邮箱"
          >
            <Input
              disabled
              placeholder="邮箱不可修改"
            />
          </Form.Item>

          {isGuest && (
            <>
              <Form.Item
                name="gender"
                label="性别"
              >
                <Select
                  placeholder="选择性别"
                  options={[
                    { value: '男', label: '男' },
                    { value: '女', label: '女' },
                    { value: '其他', label: '其他' },
                  ]}
                />
              </Form.Item>

              <Form.Item
                name="age"
                label="年龄"
              >
                <InputNumber
                  min={1}
                  max={120}
                  placeholder="年龄"
                  style={{ width: '100%' }}
                />
              </Form.Item>

              <Form.Item
                name="district"
                label="所在区县"
              >
                <Input placeholder="如：杨浦区" />
              </Form.Item>

              <Form.Item
                name="budget_per_capita"
                label="人均预算（元）"
                tooltip="用于筛选餐厅和消费场所"
              >
                <InputNumber
                  min={0}
                  max={10000}
                  step={10}
                  placeholder="人均消费预算"
                  style={{ width: '100%' }}
                  addonAfter="元"
                />
              </Form.Item>

              <Form.Item
                name="food_preferences"
                label="美食偏好"
                tooltip="输入后按回车添加标签"
              >
                <Select
                  mode="tags"
                  placeholder="如：本帮菜、咖啡、日料"
                  maxTagCount={6}
                />
              </Form.Item>
            </>
          )}
        </div>

        <Divider />

        {/* 位置偏好 */}
        <div className={styles.section}>
          <div className={styles.sectionHeader}>
            <MapPin size={16} />
            <span>位置偏好</span>
          </div>

          <Form.Item
            name="homeAddress"
            label="常住地址"
            tooltip="输入2个字后开始搜索，支持小区、写字楼、商场等"
          >
            <AutoComplete
              placeholder="请输入您的常住地址（如：陆家嘴、徐家汇）"
              options={addressOptions}
              onSelect={handleAddressSelect}
              onSearch={(value) => {
                // onSearch 在用户按下回车或点击搜索图标时触发
                // 中文输入法下，onSearch 在确认输入后触发
                handleAddressSearch(value);
              }}
              onChange={(value) => {
                // 处理清空情况
                if (!value) {
                  setSelectedAddress(null);
                  setAddressOptions([]);
                  setDropdownOpen(false);
                  return;
                }
                // 触发搜索（带防抖）
                handleAddressSearch(value);
              }}
              onFocus={handleFocus}
              notFoundContent={searchingAddress ? '搜索中...' : '请输入至少2个字进行搜索'}
              allowClear
              filterOption={false}
              open={dropdownOpen}
              onDropdownVisibleChange={(visible) => {
                // 允许用户手动关闭下拉框
                if (!visible) {
                  setDropdownOpen(false);
                } else if (addressOptions.length > 0 || searchingAddress) {
                  setDropdownOpen(true);
                }
              }}
            />
          </Form.Item>
          
          {selectedAddress && (
            <div className={styles.selectedAddress}>
              <MapPin size={14} color="#1890ff" />
              <span className={styles.selectedAddressText}>
                {selectedAddress.full_address}
              </span>
            </div>
          )}
        </div>

        <Divider />

        {/* 旅行偏好 */}
        <div className={styles.section}>
          <div className={styles.sectionHeader}>
            <Heart size={16} />
            <span>旅行偏好</span>
          </div>

          <Form.Item
            name="preferences"
            label="偏好标签（可多选）"
          >
            <Select
              mode="multiple"
              placeholder="选择您感兴趣的旅行类型"
              options={preferenceOptions}
              maxTagCount={4}
            />
          </Form.Item>
        </div>

        {/* 提交按钮 */}
        <div className={styles.actions}>
          <Button onClick={onClose}>取消</Button>
          <Button
            type="primary"
            icon={<Save size={14} />}
            onClick={handleSubmit}
            loading={loading}
            className={styles.submitBtn}
          >
            保存设置
          </Button>
        </div>
      </Form>
    </Modal>
  );
};

export default SettingsModal;
