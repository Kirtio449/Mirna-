const { createApp, ref, reactive, onMounted, nextTick, computed, watch } = Vue;

createApp({
    setup() {
        // API配置
        const API_BASE_URL = "http://127.0.0.1:5000";
        const API_ENDPOINTS = {
            REGISTER: `${API_BASE_URL}/auth/register`,
            LOGIN: `${API_BASE_URL}/auth/login`,
            USER_INFO: `${API_BASE_URL}/auth/user`,
            ANALYSIS: `${API_BASE_URL}/analysis`,
            EXPORT_PDF: `${API_BASE_URL}/export/pdf`,
            EXPORT_CSV: `${API_BASE_URL}/export/csv`,
            EXPORT_IMAGE: `${API_BASE_URL}/export/image`,
            HISTORY: `${API_BASE_URL}/history`,
            GET_ANALYSIS: `${API_BASE_URL}/analysis`,
            FORGOT_PASSWORD: `${API_BASE_URL}/auth/forgot-password`,
            VERIFY_RESET_CODE: `${API_BASE_URL}/auth/verify-reset-code`,
            RESET_PASSWORD: `${API_BASE_URL}/auth/reset-password`
        };
        
        // 状态管理
        const currentPage = ref('analysis');
        const user = ref(null);
        const authToken = ref(localStorage.getItem('authToken') || null);
        const showLoginModal = ref(false);
        const showRegisterModal = ref(false);
        const isLoading = ref(false);
        const loadingText = ref('分析中，请稍候...');
        const analysisData = ref(null);
        const currentAnalysisId = ref(null);
        const history = ref([]);
        
        // 分析相关状态
        const inputMethod = ref('manual');
        const sequence = ref('');
        const fileInfo = ref(null);
        const isDragging = ref(false);
        const fileUploadStatus = ref(null);
        const options = reactive({
            regulatoryNetwork: true,
            symptomsPrediction: true
        });
        const analysisError = ref('');
        
        // 结果相关状态
        const activeTab = ref('mirna');
        const exportStatus = reactive({
            type: '',
            message: ''
        });
        
        // 登录/注册相关状态
        const loginForm = reactive({
            username: '',
            password: '',
            remember: false
        });
        const loginStatus = reactive({
            type: '',
            message: ''
        });
        const registerForm = reactive({
            username: '',
            email: '',
            password: '',
            confirmPassword: ''
        });
        const registerStatus = reactive({
            type: '',
            message: ''
        });
        
        // 忘记密码相关状态
        const showForgotPasswordModal = ref(false);
        const showVerifyCodeModal = ref(false);
        const showResetPasswordModal = ref(false);
        const forgotPasswordForm = reactive({
            email: '',
            code: '',
            newPassword: '',
            confirmPassword: ''
        });
        const forgotPasswordStatus = reactive({
            type: '',
            message: ''
        });
        const verifyCodeStatus = reactive({
            type: '',
            message: ''
        });
        const resetPasswordStatus = reactive({
            type: '',
            message: ''
        });
        const resendDisabled = ref(false);
        const countdown = ref(60);
        const showNewPassword = ref(false);
        const showConfirmPassword = ref(false);
        
        // 初始化 Axios 拦截器 (移出 login 函数)
        axios.interceptors.request.use(config => {
            const token = localStorage.getItem('authToken');
            if (token) {
                config.headers.Authorization = `Bearer ${token}`;
            }
            return config;
        });
        axios.interceptors.response.use(
            response => response,
            error => {
                if (error.response && error.response.status === 401) {
                    // 1. 清除本地存储的失效 token
                    localStorage.removeItem('authToken');
                    authToken.value = null;
                    user.value = null;

                    // 2. 如果不是在登录操作中遇到的错误，则提示用户
                    if (!error.config.url.includes('/auth/login')) {
                        alert('登录已过期，请重新登录');
                        showLoginModal.value = true; // 自动弹出登录框
                    }
                }
                return Promise.reject(error);
            }
        );
        // 密码强度计算
        const passwordStrength = computed(() => {
            if (!forgotPasswordForm.newPassword) return 0;

            let strength = 0;
            const password = forgotPasswordForm.newPassword;

            // 长度评分
            if (password.length >= 8) strength += 25;
            if (password.length >= 12) strength += 15;

            // 包含小写字母
            if (/[a-z]/.test(password)) strength += 10;

            // 包含大写字母
            if (/[A-Z]/.test(password)) strength += 10;

            // 包含数字
            if (/\d/.test(password)) strength += 20;

            // 包含特殊字符
            if (/[^A-Za-z0-9]/.test(password)) strength += 20;

            return Math.min(strength, 100);
        });

        const passwordStrengthText = computed(() => {
            if (passwordStrength.value < 30) return "弱";
            if (passwordStrength.value < 70) return "中等";
            return "强";
        });

        const passwordStrengthClass = computed(() => {
            if (passwordStrength.value < 30) return "weak";
            if (passwordStrength.value < 70) return "medium";
            return "strong";
        });

        // 监听密码变化更新强度
        watch(() => forgotPasswordForm.newPassword, () => {
            // 自动计算密码强度
        });

        // 页面导航
        const showPage = (page) => {
            currentPage.value = page;
            if (page === 'history') {
                loadHistory();
            }
        };

        // 用户认证相关方法
        const login = async () => {
            if (!loginForm.username || !loginForm.password) {
                loginStatus.type = 'error';
                loginStatus.message = '请输入用户名和密码';
                return;
            }

            isLoading.value = true;
            loadingText.value = '登录中...';

            try {
                const response = await axios.post(API_ENDPOINTS.LOGIN, {
                    username: loginForm.username,
                    password: loginForm.password
                });

                if (response.data.success) {
                    authToken.value = response.data.access_token;
                    localStorage.setItem('authToken', authToken.value);
                    user.value = response.data.user;

                    loginStatus.type = 'success';
                    loginStatus.message = '登录成功！';

                    setTimeout(() => {
                        showLoginModal.value = false;
                        isLoading.value = false;
                    }, 1000);
                } else {
                    loginStatus.type = 'error';
                    loginStatus.message = response.data.message || '登录失败';
                    isLoading.value = false;
                }
            } catch (error) {
                console.error('登录失败:', error);
                loginStatus.type = 'error';
                loginStatus.message = '登录失败: ' + (error.response?.data?.message || error.message);
                isLoading.value = false;
            }
        };

        const register = async () => {
            if (!registerForm.username || !registerForm.email || !registerForm.password) {
                registerStatus.type = 'error';
                registerStatus.message = '请填写所有必填字段';
                return;
            }

            if (registerForm.password !== registerForm.confirmPassword) {
                registerStatus.type = 'error';
                registerStatus.message = '两次输入的密码不一致';
                return;
            }

            if (registerForm.password.length < 8) {
                registerStatus.type = 'error';
                registerStatus.message = '密码长度至少为8位';
                return;
            }

            isLoading.value = true;
            loadingText.value = '注册中...';

            try {
                const response = await axios.post(API_ENDPOINTS.REGISTER, {
                    username: registerForm.username,
                    email: registerForm.email,
                    password: registerForm.password,
                    confirmPassword: registerForm.confirmPassword
                });

                if (response.data.success) {
                    authToken.value = response.data.access_token;
                    localStorage.setItem('authToken', authToken.value);
                    user.value = response.data.user;

                    registerStatus.type = 'success';
                    registerStatus.message = '注册成功！';

                    setTimeout(() => {
                        showRegisterModal.value = false;
                        isLoading.value = false;
                    }, 1000);
                } else {
                    registerStatus.type = 'error';
                    registerStatus.message = response.data.message || '注册失败';
                    isLoading.value = false;
                }
            } catch (error) {
                console.error('注册失败:', error);
                registerStatus.type = 'error';
                registerStatus.message = '注册失败: ' + (error.response?.data?.message || error.message);
                isLoading.value = false;
            }
        };

        const logout = () => {
            user.value = null;
            authToken.value = null;
            localStorage.removeItem('authToken');
        };

        const showRegister = () => {
            showLoginModal.value = false;
            showRegisterModal.value = true;
        };

        // 忘记密码功能
        const showForgotPassword = () => {
            showLoginModal.value = false;
            showForgotPasswordModal.value = true;
            forgotPasswordStatus.type = '';
            forgotPasswordStatus.message = '';
            forgotPasswordForm.email = '';
        };

        const sendResetCode = async () => {
            if (!forgotPasswordForm.email) {
                forgotPasswordStatus.type = 'error';
                forgotPasswordStatus.message = '请输入电子邮箱';
                return;
            }

            // 简单的邮箱格式验证
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (!emailRegex.test(forgotPasswordForm.email)) {
                forgotPasswordStatus.type = 'error';
                forgotPasswordStatus.message = '请输入有效的电子邮箱';
                return;
            }

            isLoading.value = true;
            loadingText.value = '发送验证码中...';

            try {
                // 模拟API调用
                const response = await axios.post(API_ENDPOINTS.FORGOT_PASSWORD, {
                    email: forgotPasswordForm.email
                });

                if (response.data.success) {
                    forgotPasswordStatus.type = 'success';
                    forgotPasswordStatus.message = '验证码已发送到您的邮箱';

                    // 显示验证码输入界面
                    showForgotPasswordModal.value = false;
                    showVerifyCodeModal.value = true;

                    // 开始倒计时
                    startCountdown();
                } else {
                    forgotPasswordStatus.type = 'error';
                    forgotPasswordStatus.message = response.data.message || '发送验证码失败';
                }
            } catch (error) {
                console.error('发送验证码失败:', error);
                forgotPasswordStatus.type = 'error';
                forgotPasswordStatus.message = '发送验证码失败: ' + (error.response?.data?.message || error.message);
            } finally {
                isLoading.value = false;
            }
        };

        const startCountdown = () => {
            resendDisabled.value = true;
            countdown.value = 60;

            const timer = setInterval(() => {
                countdown.value--;
                if (countdown.value <= 0) {
                    clearInterval(timer);
                    resendDisabled.value = false;
                }
            }, 1000);
        };

        const resendCode = async () => {
            if (resendDisabled.value) return;

            try {
                // 模拟重新发送验证码
                const response = await axios.post(API_ENDPOINTS.FORGOT_PASSWORD, {
                    email: forgotPasswordForm.email
                });

                if (response.data.success) {
                    verifyCodeStatus.type = 'success';
                    verifyCodeStatus.message = '验证码已重新发送';

                    // 重新开始倒计时
                    startCountdown();
                } else {
                    verifyCodeStatus.type = 'error';
                    verifyCodeStatus.message = response.data.message || '重新发送验证码失败';
                }
            } catch (error) {
                console.error('重新发送验证码失败:', error);
                verifyCodeStatus.type = 'error';
                verifyCodeStatus.message = '重新发送验证码失败: ' + (error.response?.data?.message || error.message);
            }
        };

        const verifyResetCode = async () => {
            if (!forgotPasswordForm.code) {
                verifyCodeStatus.type = 'error';
                verifyCodeStatus.message = '请输入验证码';
                return;
            }

            if (forgotPasswordForm.code.length !== 6) {
                verifyCodeStatus.type = 'error';
                verifyCodeStatus.message = '验证码必须是6位数字';
                return;
            }

            isLoading.value = true;
            loadingText.value = '验证中...';

            try {
                // 模拟验证码验证
                const response = await axios.post(API_ENDPOINTS.VERIFY_RESET_CODE, {
                    email: forgotPasswordForm.email,
                    code: forgotPasswordForm.code
                });

                if (response.data.success) {
                    // 显示重置密码界面
                    showVerifyCodeModal.value = false;
                    showResetPasswordModal.value = true;
                    resetPasswordStatus.type = '';
                    resetPasswordStatus.message = '';
                } else {
                    verifyCodeStatus.type = 'error';
                    verifyCodeStatus.message = response.data.message || '验证码错误';
                }
            } catch (error) {
                console.error('验证失败:', error);
                verifyCodeStatus.type = 'error';
                verifyCodeStatus.message = '验证失败: ' + (error.response?.data?.message || error.message);
            } finally {
                isLoading.value = false;
            }
        };

        const resetPassword = async () => {
            if (!forgotPasswordForm.newPassword) {
                resetPasswordStatus.type = 'error';
                resetPasswordStatus.message = '请输入新密码';
                return;
            }

            if (forgotPasswordForm.newPassword.length < 8) {
                resetPasswordStatus.type = 'error';
                resetPasswordStatus.message = '密码长度至少为8位';
                return;
            }

            if (forgotPasswordForm.newPassword !== forgotPasswordForm.confirmPassword) {
                resetPasswordStatus.type = 'error';
                resetPasswordStatus.message = '两次输入的密码不一致';
                return;
            }

            isLoading.value = true;
            loadingText.value = '重置密码中...';

            try {
                // 模拟重置密码
                const response = await axios.post(API_ENDPOINTS.RESET_PASSWORD, {
                    email: forgotPasswordForm.email,
                    code: forgotPasswordForm.code,
                    newPassword: forgotPasswordForm.newPassword
                });

                if (response.data.success) {
                    resetPasswordStatus.type = 'success';
                    resetPasswordStatus.message = '密码重置成功！';

                    // 重置表单
                    forgotPasswordForm.newPassword = '';
                    forgotPasswordForm.confirmPassword = '';

                    // 2秒后关闭模态框
                    setTimeout(() => {
                        showResetPasswordModal.value = false;
                        isLoading.value = false;

                        // 显示登录界面
                        showLoginModal.value = true;
                    }, 2000);
                } else {
                    resetPasswordStatus.type = 'error';
                    resetPasswordStatus.message = response.data.message || '密码重置失败';
                    isLoading.value = false;
                }
            } catch (error) {
                console.error('密码重置失败:', error);
                resetPasswordStatus.type = 'error';
                resetPasswordStatus.message = '密码重置失败: ' + (error.response?.data?.message || error.message);
                isLoading.value = false;
            }
        };

        const backToEmailStep = () => {
            showVerifyCodeModal.value = false;
            showForgotPasswordModal.value = true;
        };

        const backToCodeStep = () => {
            showResetPasswordModal.value = false;
            showVerifyCodeModal.value = true;
        };

        // 文件处理相关方法
        const triggerFileInput = () => {
            document.getElementById('file-input').click();
        };

        const handleFileChange = (e) => {
            if (e.target.files.length > 0) {
                const file = e.target.files[0];
                processFile(file);
            }
        };

        const handleDrop = (e) => {
            isDragging.value = false;
            if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                const file = e.dataTransfer.files[0];
                processFile(file);
            }
        };

        const processFile = (file) => {
            // 验证文件类型
            const validExtensions = ['.fasta', '.fa', '.txt'];
            const fileExt = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();

            if (!validExtensions.includes(fileExt)) {
                fileUploadStatus.value = {
                    type: 'error',
                    message: '不支持的文件格式！请上传FASTA或TXT文件'
                };
                return;
            }

            // 验证文件大小
            if (file.size > 10 * 1024 * 1024) {
                fileUploadStatus.value = {
                    type: 'error',
                    message: '文件大小超过限制（最大10MB）'
                };
                return;
            }

            fileInfo.value = {
                name: file.name,
                size: formatFileSize(file.size),
                type: getFileType(file.name),
                file: file
            };

            fileUploadStatus.value = {
                type: 'success',
                message: '文件已成功上传'
            };
        };

        const formatFileSize = (bytes) => {
            if (bytes === 0) return '0 Bytes';
            const k = 1024;
            const sizes = ['Bytes', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        };

        const getFileType = (filename) => {
            const ext = filename.split('.').pop().toLowerCase();
            if (ext === 'fasta' || ext === 'fa') return 'FASTA';
            if (ext === 'txt') return 'TXT';
            return ext.toUpperCase();
        };

        // 分析相关方法
        const loadExample = () => {
            inputMethod.value = 'manual';
            sequence.value = ">SARS-CoV-2 Spike Protein\n" +
                "ATGTTCGTGTTACCTAAAGTTTTAACGCGAATTTTAACAAAATACATTAAAGCTTTAAAGTTGTTGTTAAAGTTACAGCTAGTTGTTAAAGTTGTTGTTAAAGTTACAGCTAGTTGTTAAAGTTGTTGTTAAAGTTACAGCTAGTTGTTAAAGTTGTTGTTAAAGTTACAGCTAGTTGTTAAAGTTGTTGTTAAAGTTACAGCTAGTTGTTAAAGTTGTT";
            fileInfo.value = null;
            analysisError.value = '';
        };

        const analyzeSequence = async () => {
            if (!sequence.value && !fileInfo.value) {
                analysisError.value = '请先输入RNA序列或上传文件';
                return;
            }

            isLoading.value = true;
            loadingText.value = '分析中，请稍候...';
            analysisError.value = '';

            try {
                const formData = new FormData();

                if (fileInfo.value) {
                    formData.append('file', fileInfo.value.file);
                } else {
                    formData.append('sequence', sequence.value);
                }

                formData.append('options', JSON.stringify(options));

                const response = await axios.post(API_ENDPOINTS.ANALYSIS, formData, {
                    headers: {
                        'Content-Type': 'multipart/form-data',
                        // 注意：这里不需要手动设置 Authorization，因为拦截器会处理
                    }
                });

                if (response.data.success) {
                    analysisData.value = response.data.data;
                    currentAnalysisId.value = response.data.analysis_id;
                    currentPage.value = 'results';

                    // 添加到历史记录
                    history.value.unshift({
                        id: response.data.analysis_id,
                        date: new Date().toLocaleString(),
                        sequencePreview: sequence.value.substring(0, 50) + (sequence.value.length > 50 ? '...' : ''),
                        data: response.data.data
                    });

                    // 渲染图表
                    nextTick(() => {
                        renderMiRNAChart();
                        renderNetworkGraph();
                    });
                } else {
                    analysisError.value = response.data.message || '分析失败';
                }
            } catch (error) {
                console.error('分析失败:', error);
                analysisError.value = '分析失败: ' + (error.response?.data?.message || error.message);
            } finally {
                isLoading.value = false;
            }
        };

        // 历史记录方法
        const loadHistory = async () => {
            if (!user.value) return;

            try {
                const response = await axios.get(`${API_BASE_URL}/history`);

                if (response.data.success) {
                    history.value = response.data.records.map(record => ({
                        id: record.id,
                        date: record.date, // 修复：使用 backend 返回的 formatted date
                        sequencePreview: record.sequencePreview,
                        data: {} // 历史记录列表不需要加载完整数据，查看时再加载详情
                    }));
                }
            } catch (error) {
                console.error('加载历史记录失败:', error);
            }
        };

        const viewAnalysis = (item) => {
            // 如果本地没有数据，需要从后端获取完整分析结果
            if (!item.data || Object.keys(item.data).length === 0) {
                 axios.get(`${API_BASE_URL}/analysis/${item.id}`)
                    .then(response => {
                        if (response.data.success) {
                             analysisData.value = response.data.data;
                             currentAnalysisId.value = item.id;
                             currentPage.value = 'results';
                             nextTick(() => {
                                renderMiRNAChart();
                                renderNetworkGraph();
                            });
                        }
                    })
                    .catch(err => console.error("加载详情失败", err));
            } else {
                analysisData.value = item.data;
                currentAnalysisId.value = item.id;
                currentPage.value = 'results';
                nextTick(() => {
                    renderMiRNAChart();
                    renderNetworkGraph();
                });
            }
        };

        const deleteAnalysis = async (index) => {
            const id = history.value[index].id;
            // 注意：API 似乎没有实现 DELETE 路由，这里仅做前端移除演示
            // 实际使用请在 app.py 添加 DELETE 路由
            history.value.splice(index, 1);
        };

        // 结果可视化
        const renderMiRNAChart = () => {
            const ctx = document.getElementById('miRNAChart').getContext('2d');
            new Chart(ctx, {
                type: 'pie',
                data: {
                    labels: ['高置信度', '中置信度', '低置信度'],
                    datasets: [{
                        data: [
                            analysisData.value.mirna_distribution.high,
                            analysisData.value.mirna_distribution.medium,
                            analysisData.value.mirna_distribution.low
                        ],
                        backgroundColor: [
                            '#4da6ff',
                            '#8cb3d9',
                            '#ff6b6b'
                        ],
                        borderWidth: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'bottom',
                            labels: {
                                font: {
                                    size: 12
                                }
                            }
                        }
                    }
                }
            });
        };

        const renderNetworkGraph = () => {
            const container = document.querySelector('.network-container');
            if (!container || !window.cytoscape) return;

            cytoscape({
                container: container,
                style: [
                    {
                        selector: 'node',
                        style: {
                            'background-color': '#4da6ff',
                            'label': 'data(name)',
                            'text-valign': 'center',
                            'text-halign': 'center',
                            'color': '#fff',
                            'font-size': '10px',
                            'width': '40',
                            'height': '40'
                        }
                    },
                    {
                        selector: 'node[type="mirna"]',
                        style: {
                            'background-color': '#00cc99',
                            'shape': 'hexagon'
                        }
                    },
                    {
                        selector: 'node[type="gene"]',
                        style: {
                            'background-color': '#ff6b6b',
                            'shape': 'ellipse'
                        }
                    },
                    {
                        selector: 'node[type="symptom"]',
                        style: {
                            'background-color': '#ffd166',
                            'shape': 'triangle'
                        }
                    },
                    {
                        selector: 'edge',
                        style: {
                            'width': 2,
                            'line-color': '#8cb3d9',
                            'target-arrow-color': '#8cb3d9',
                            'target-arrow-shape': 'triangle',
                            'curve-style': 'bezier',
                            'arrow-scale': 1.5
                        }
                    }
                ],
                // 简化演示数据
                elements: {
                    nodes: [
                        { data: { id: 'm1', name: 'miR-1', type: 'mirna' } },
                        { data: { id: 'm2', name: 'miR-2', type: 'mirna' } },
                        { data: { id: 'g1', name: 'Gene A', type: 'gene' } },
                        { data: { id: 'g2', name: 'Gene B', type: 'gene' } },
                        { data: { id: 's1', name: 'Symptom X', type: 'symptom' } }
                    ],
                    edges: [
                        { data: { source: 'm1', target: 'g1' } },
                        { data: { source: 'm1', target: 'g2' } },
                        { data: { source: 'm2', target: 'g1' } },
                        { data: { source: 'g1', target: 's1' } }
                    ]
                },
                layout: {
                    name: 'circle', // 使用简单的布局防止计算量过大
                    animate: false
                }
            });
        };

        // 结果导出
        const exportResult = async (type) => {
            if (!user.value) {
                exportStatus.type = 'error';
                exportStatus.message = '请先登录以导出结果';
                return;
            }

            if (!currentAnalysisId.value) {
                exportStatus.type = 'error';
                exportStatus.message = '没有可导出的分析结果';
                return;
            }

            exportStatus.type = 'loading';
            exportStatus.message = `正在导出${type.toUpperCase()}...`;

            try {
                let endpoint;
                switch (type) {
                    case 'pdf': endpoint = API_ENDPOINTS.EXPORT_PDF; break;
                    case 'csv': endpoint = API_ENDPOINTS.EXPORT_CSV; break;
                    case 'image': endpoint = API_ENDPOINTS.EXPORT_IMAGE; break;
                    default: return;
                }

                const response = await axios.get(`${endpoint}/${currentAnalysisId.value}`, {
                    responseType: 'blob'
                });

                const url = window.URL.createObjectURL(response.data);
                const a = document.createElement('a');
                a.href = url;
                a.download = `covid-mirna-analysis-${currentAnalysisId.value}.${type}`;
                document.body.appendChild(a);
                a.click();
                a.remove();

                exportStatus.type = 'success';
                exportStatus.message = `${type.toUpperCase()}导出成功！`;
            } catch (error) {
                console.error(`导出${type.toUpperCase()}失败:`, error);
                exportStatus.type = 'error';
                exportStatus.message = `导出${type.toUpperCase()}失败: ${error.response?.data?.message || error.message}`;
            } finally {
                setTimeout(() => {
                    exportStatus.type = '';
                    exportStatus.message = '';
                }, 3000);
            }
        };

        // 辅助方法
        const getConfidenceColor = (confidence) => {
            switch(confidence.toLowerCase()) {
                case '高': return '#4da6ff';
                case '中': return '#ffd166';
                case '低': return '#ff6b6b';
                default: return '#333';
            }
        };

        const getEvidenceColor = (strength) => {
            switch(strength.toLowerCase()) {
                case '强': return '#4da6ff';
                case '中等': return '#ffd166';
                case '弱': return '#ff6b6b';
                default: return '#333';
            }
        };

        // 初始化用户状态
        onMounted(async () => {
            if (authToken.value) {
                try {
                    const response = await axios.get(API_ENDPOINTS.USER_INFO);

                    if (response.data.success) {
                        user.value = response.data.user;
                    } else {
                        localStorage.removeItem('authToken');
                    }
                } catch (error) {
                    console.error('获取用户信息失败:', error);
                    localStorage.removeItem('authToken');
                }
            }
        });

        return {
            // 状态
            currentPage,
            user,
            showLoginModal,
            showRegisterModal,
            isLoading,
            loadingText,
            analysisData,
            inputMethod,
            sequence,
            fileInfo,
            isDragging,
            fileUploadStatus,
            options,
            analysisError,
            activeTab,
            exportStatus,
            loginForm,
            loginStatus,
            registerForm,
            registerStatus,
            history,
            showForgotPasswordModal,
            showVerifyCodeModal,
            showResetPasswordModal,
            forgotPasswordForm,
            forgotPasswordStatus,
            verifyCodeStatus,
            resetPasswordStatus,
            resendDisabled,
            countdown,
            showNewPassword,
            showConfirmPassword,
            passwordStrength,
            passwordStrengthText,
            passwordStrengthClass,

            // 方法
            showPage,
            login,
            register,
            logout,
            showRegister,
            triggerFileInput,
            handleFileChange,
            handleDrop,
            loadExample,
            analyzeSequence,
            exportResult,
            getConfidenceColor,
            getEvidenceColor,
            viewAnalysis,
            deleteAnalysis,
            showForgotPassword,
            sendResetCode,
            resendCode,
            verifyResetCode,
            resetPassword,
            backToEmailStep,
            backToCodeStep
        };
    }
}).mount('#app');