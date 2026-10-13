"""功能模块集合。

业务功能以「包」为单位切分，每个子包（projects、environment_configuration、
model_configuration 等）自带 router / schemas / service 三层，彼此互不感知：
router 只做参数与认证、schemas 定义契约、service 承载业务与事务。
本文件由 app.main 在注册路由时引用，不需要导出具体符号。
"""
