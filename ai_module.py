# ai_module.py
import jieba
from collections import defaultdict
import logging
import re

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MedicalAI:
    def __init__(self):
        """Initializes the enhanced medical AI analyzer."""
        # Extended medical keyword library
        self.keywords = {
            'diseases': ['感冒', '流感', '发烧', '高血压', '低血压', '冠心病', '心肌梗塞',
                         '糖尿病', 'I型糖尿病', 'II型糖尿病', '癌症', '肺癌', '乳腺癌',
                         '胃癌', '肝癌', 'HIV', '艾滋病', '新冠肺炎', 'COVID-19', '肺炎',
                         '支气管炎', '哮喘', '肺结核', '胃炎', '胃溃疡', '肠炎', '肝炎',
                         '肾炎', '肾结石', '关节炎', '骨质疏松', '抑郁症', '焦虑症',
                         '精神分裂症', '阿尔茨海默病', '帕金森病', '癫痫', '中风',
                         '白内障', '青光眼', '湿疹', '牛皮癣', '白癜风'],
            'treatments': ['服药', '输液', '注射', '手术', '微创手术', '化疗', '放疗',
                           '靶向治疗', '免疫治疗', '胰岛素', '住院', 'ICU', '康复治疗',
                           '物理治疗', '心理治疗', '中医治疗', '针灸', '推拿', '透析',
                           '器官移植', '基因治疗'],
            'symptoms': ['头痛', '头晕', '发热', '咳嗽', '咳血', '胸闷', '胸痛', '心悸',
                         '呼吸困难', '恶心', '呕吐', '腹泻', '便秘', '血便', '腹痛',
                         '关节痛', '肌肉酸痛', '皮疹', '瘙痒', '视力模糊', '耳鸣', '乏力',
                         '消瘦', '肥胖', '失眠', '焦虑', '抑郁', '记忆减退', '意识模糊',
                         '血糖升高', '多饮'],
            'sensitive': ['艾滋病', '精神疾病', 'HIV', '性病', '梅毒', '淋病', '吸毒',
                          '自杀倾向', '暴力倾向', '遗传病', '先天缺陷']
        }

        # Add medical terms to jieba dictionary
        for category in self.keywords:
            for term in self.keywords[category]:
                jieba.add_word(term)

        # Disease risk weights (example values)
        self.disease_weights = {
            '感冒': 0.1, '流感': 0.2, '发烧': 0.2, '高血压': 0.4, '低血压': 0.3, '冠心病': 0.6,
            '心肌梗塞': 0.8, '糖尿病': 0.5, 'I型糖尿病': 0.6, 'II型糖尿病': 0.5, '癌症': 0.9,
            '肺癌': 0.9, '乳腺癌': 0.8, '胃癌': 0.85, '肝癌': 0.95, 'HIV': 0.95, '艾滋病': 0.95,
            '新冠肺炎': 0.7, 'COVID-19': 0.7, '肺炎': 0.6, '支气管炎': 0.4, '哮喘': 0.5,
            '肺结核': 0.7, '胃炎': 0.3, '胃溃疡': 0.4, '肠炎': 0.3, '肝炎': 0.6, '肾炎': 0.5,
            '肾结石': 0.4, '关节炎': 0.3, '骨质疏松': 0.3, '抑郁症': 0.5, '焦虑症': 0.4,
            '精神分裂症': 0.7, '阿尔茨海默病': 0.6, '帕金森病': 0.7, '癫痫': 0.6, '中风': 0.8,
            '白内障': 0.3, '青光眼': 0.4, '湿疹': 0.2, '牛皮癣': 0.3, '白癜风': 0.2
        }

        # Treatment risk multipliers (example values)
        self.treatment_weights = {
            '服药': 0.1, '输液': 0.2, '注射': 0.2, '手术': 0.6, '微创手术': 0.4, '化疗': 0.8,
            '放疗': 0.7, '靶向治疗': 0.5, '免疫治疗': 0.5, '胰岛素': 0.3, '住院': 0.4, 'ICU': 0.9,
            '康复治疗': 0.2, '物理治疗': 0.2, '心理治疗': 0.2, '中医治疗': 0.1, '针灸': 0.1,
            '推拿': 0.1, '透析': 0.7, '器官移植': 0.95, '基因治疗': 0.8
        }

        # Sensitivity levels
        self.sensitivity_levels = {
            '艾滋病': 'high', 'HIV': 'high', '精神疾病': 'high', '性病': 'high',
            '梅毒': 'high', '淋病': 'high', '吸毒': 'high', '自杀倾向': 'high',
            '暴力倾向': 'high', '遗传病': 'medium', '先天缺陷': 'medium'
        }

        logging.info("MedicalAI initialized successfully.")

    def _preprocess_text(self, text):
        """Preprocesses the input text."""
        if not isinstance(text, str):
            return ""
        # Remove non-word characters (excluding Chinese characters) and normalize spaces
        text = re.sub(r'[^\w\u4e00-\u9fff]+', ' ', text)
        # Convert to lowercase and strip whitespace
        return text.lower().strip()

    def _extract_entities(self, text):
        """Extracts entities using jieba and predefined keywords."""
        words = jieba.lcut(text)
        entities = defaultdict(list)
        all_terms = {term for cat_terms in self.keywords.values() for term in cat_terms}

        for word in words:
            if word in all_terms:
                for category, terms in self.keywords.items():
                    if word in terms:
                        entities[category].append(word)
                        # Optimization: if found, no need to check other categories for this word
                        # break # Removing break allows a term to be in multiple categories if defined so

        # Deduplicate entities within each category
        for category in entities:
            entities[category] = sorted(list(set(entities[category])))

        return dict(entities)

    def _contextual_analysis(self, entities, text):
        """Performs basic contextual analysis (e.g., negation detection)."""
        # Simple negation check
        negation_words = {'不', '没', '无', '未', '非'}
        if any(neg_word in text for neg_word in negation_words):
            entities['negation_context'] = True
        else:
            entities['negation_context'] = False

    def _calculate_enhanced_risk(self, entities):
        """Calculates an enhanced risk score based on entities."""
        base_risk = 0.1 # Start with a lower base risk
        risk_score = base_risk

        # Calculate risk from diseases and treatments
        disease_risk = sum(self.disease_weights.get(d, 0.05) for d in entities.get('diseases', []))
        treatment_risk = sum(self.treatment_weights.get(t, 0.05) for t in entities.get('treatments', []))

        # Factor in symptom count, capping the contribution
        symptom_risk = min(0.3, len(entities.get('symptoms', [])) * 0.03)

        # Combine risks (adjust multipliers as needed)
        risk_score += disease_risk * 0.4 + treatment_risk * 0.3 + symptom_risk

        # Adjust risk based on negation context
        if entities.get('negation_context', False):
            risk_score *= 0.6 # Reduce risk more significantly if negation detected

        # Normalize the score between 0.01 and 0.99
        return max(0.01, min(0.99, risk_score))

    def _assess_enhanced_sensitivity(self, entities):
        """Assesses the sensitivity level based on identified sensitive terms."""
        max_level = 'low'
        sensitive_found = entities.get('sensitive', [])

        if not sensitive_found:
            return 'low'

        for term in sensitive_found:
            level = self.sensitivity_levels.get(term)
            if level == 'high':
                return 'high' # High sensitivity overrides others
            elif level == 'medium':
                max_level = 'medium' # Track if medium is found

        return max_level

    def _generate_diagnosis_suggestions(self, entities):
        """Generates diagnosis suggestions based on symptoms and diseases."""
        symptoms = set(entities.get('symptoms', []))
        suggestions = []

        if {'咳嗽', '发热'}.issubset(symptoms):
            suggestions.append("考虑呼吸道感染可能")
        if {'胸痛', '呼吸困难'}.issubset(symptoms):
            suggestions.append("需排除心血管疾病")
        if {'血糖升高', '多饮'}.issubset(symptoms):
            suggestions.append("建议糖尿病筛查")
        # Add more rules as needed

        return suggestions if suggestions else ["根据症状建议进一步检查"]

    def _generate_treatment_suggestions(self, entities):
        """Generates treatment suggestions based on diagnoses and existing treatments."""
        diseases = set(entities.get('diseases', []))
        treatments = set(entities.get('treatments', []))
        suggestions = []

        if '高血压' in diseases and '服药' not in treatments:
            suggestions.append("建议考虑降压药物治疗")
        if '糖尿病' in diseases and '胰岛素' not in treatments:
            suggestions.append("建议血糖监测及胰岛素治疗方案评估")
        if '癌症' in diseases and '化疗' not in treatments and '手术' not in treatments:
            suggestions.append("建议肿瘤专科会诊评估治疗方案（如化疗、手术等）")
        # Add more rules as needed

        return suggestions if suggestions else ["根据诊断建议制定个性化治疗方案"]

    def _get_safe_default(self, patient_name=None):
        """Returns a safe default result structure."""
        return {
            'diagnosis': ['分析失败'],
            'diagnosis_suggestions': ['需人工复核'],
            'treatment': ['待制定'],
            'treatment_suggestions': ['需医生评估'],
            'symptoms': [],
            'risk_score': 0.5, # Default neutral risk
            'sensitivity_level': 'medium', # Default medium sensitivity on error
            'entities': {},
            'patient_name': patient_name if patient_name else "未知"
        }

    def analyze_text(self, text, patient_name=None):
        """Analyzes medical text to extract entities, assess risk, and provide suggestions."""
        if not text or not isinstance(text, str):
             logging.warning("Analysis attempted on empty or invalid text input.")
             return self._get_safe_default(patient_name)

        try:
            # 1. Preprocess
            processed_text = self._preprocess_text(text)
            if not processed_text:
                logging.warning("Text became empty after preprocessing.")
                return self._get_safe_default(patient_name)

            # 2. Extract Entities
            entities = self._extract_entities(processed_text)

            # 3. Contextual Analysis
            self._contextual_analysis(entities, processed_text)

            # 4. Calculate Risk
            risk_score = self._calculate_enhanced_risk(entities)

            # 5. Assess Sensitivity
            sensitivity_level = self._assess_enhanced_sensitivity(entities)

            # 6. Generate Suggestions
            diagnosis_suggestions = self._generate_diagnosis_suggestions(entities)
            treatment_suggestions = self._generate_treatment_suggestions(entities)

            # 7. Format Result
            result = {
                'diagnosis': entities.get('diseases', ['未识别明确诊断']),
                'diagnosis_suggestions': diagnosis_suggestions,
                'treatment': entities.get('treatments', ['未识别明确治疗']),
                'treatment_suggestions': treatment_suggestions,
                'symptoms': entities.get('symptoms', []),
                'risk_score': risk_score,
                'sensitivity_level': sensitivity_level,
                'entities': entities, # Include extracted entities
                'patient_name': patient_name if patient_name else entities.get('patient_name', "未知")
            }
            return result

        except Exception as e:
            logging.error(f"Error during medical text analysis: {str(e)}", exc_info=True)
            return self._get_safe_default(patient_name)