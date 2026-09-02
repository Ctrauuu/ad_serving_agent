import http from './http'

export const getCampaigns = (params) => http.get('/campaigns', { params })
export const getProducts = () => http.get('/products')
export const createCampaign = (data) => http.post('/campaigns', data)
export const updateCampaign = (id, data) => http.put(`/campaigns/${id}`, data)
export const parseGoal = (id) => http.post(`/campaigns/${id}/parse-goal`)
