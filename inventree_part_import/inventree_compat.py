# Compatibility patches for InvenTree 1.x API changes.
# In InvenTree 1.0, Parameter and ParameterTemplate moved from part/ to the root,
# and PartCategoryParameterTemplate renamed its field from parameter_template_detail
# to template_detail.
import inventree.part as _part

if _part.Parameter.URL.startswith('part/'):
    _part.Parameter.URL = 'parameter/'

if _part.ParameterTemplate.URL.startswith('part/'):
    _part.ParameterTemplate.URL = 'parameter/template/'
