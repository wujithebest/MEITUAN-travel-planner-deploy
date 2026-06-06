/** 统一兜底常量 — 同济大学四平路校区 */
export const FALLBACK_HOME_LOCATION = {
  lat: 31.2809,
  lng: 121.5011,
  label: '同济大学四平路校区',
};

export const FALLBACK_HOME_ADDRESS = {
  name: '同济大学四平路校区',
  full_address: '同济大学四平路校区',
  lng: 121.5011,
  lat: 31.2809,
};

export const makeDeviceHomeAddress = (lat: number, lng: number) => ({
  name: '当前设备位置',
  full_address: '当前设备位置',
  lng,
  lat,
});

export const makeLocationPayload = (lat: number, lng: number, label = '常住地址') => ({
  lat,
  lng,
  label,
});
