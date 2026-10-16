// 类型定义

export interface Location {
  longitude: number
  latitude: number
}

export interface Attraction {
  name: string
  address: string
  location: Location
  visit_duration: number
  description: string
  category?: string
  rating?: number
  photos?: string[]
  poi_id?: string
  image_url?: string
  ticket_price?: number

  // ===== TravelMind 增量字段(全部可选,兼容旧后端返回) =====
  /** 计划内稳定节点 ID,重规划/修复时用于定位 */
  uid?: string
  /** 计划到达时间(带时区 ISO8601),缺失表示未排时间 */
  planned_start?: string
  /** 计划离开时间(带时区 ISO8601) */
  planned_end?: string
  /** POI 可核验状态 */
  verification_status?: 'verified' | 'unverified' | 'unknown'
  /** 价格来源状态:quoted=真实报价 estimated=估算 unknown=未知 */
  price_status?: 'quoted' | 'estimated' | 'unknown'
  /** 是否需要预约,undefined/NULL 表示未知 */
  requires_reservation?: boolean | null
  /** 用户是否已确认预约 */
  reservation_confirmed?: boolean
  /** 用户锁定,重规划不可修改/删除 */
  locked?: boolean
  /** 已完成节点,重规划不可修改 */
  completed?: boolean
  /** 优先级,数值越小越容易被牺牲 */
  priority?: number | null
}

export interface Meal {
  type: 'breakfast' | 'lunch' | 'dinner' | 'snack'
  name: string
  address?: string
  location?: Location
  description?: string
  estimated_cost?: number
}

export interface Hotel {
  name: string
  address: string
  location?: Location
  price_range: string
  rating: string
  distance: string
  type: string
  estimated_cost?: number
}

export interface Budget {
  total_attractions: number
  total_hotels: number
  total_meals: number
  total_transportation: number
  total: number
}

export interface DayPlan {
  date: string
  day_index: number
  description: string
  transportation: string
  accommodation: string
  hotel?: Hotel
  attractions: Attraction[]
  meals: Meal[]
}

export interface WeatherInfo {
  date: string
  day_weather: string
  night_weather: string
  day_temp: number
  night_temp: number
  wind_direction: string
  wind_power: string
}

export interface TripPlan {
  city: string
  start_date: string
  end_date: string
  days: DayPlan[]
  weather_info: WeatherInfo[]
  overall_suggestions: string
  budget?: Budget

  // ===== TravelMind 增量字段(可选,兼容旧行程数据) =====
  /** 计划 ID(旧行程可能没有,由后端规范化时补齐) */
  plan_id?: string
  /** 客户端方案版本号,用于预览/应用的乐观并发控制 */
  revision?: number
}

export interface TripFormData {
  city: string
  start_date: string
  end_date: string
  travel_days: number
  transportation: string
  accommodation: string
  preferences: string[]
  free_text_input: string
}

export interface TripPlanResponse {
  success: boolean
  message: string
  data?: TripPlan
}

