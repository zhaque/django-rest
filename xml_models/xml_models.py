"""
Copyright 2009 Chris Tarttelin and Point2 Technologies

Redistribution and use in source and binary forms, with or without modification, are
permitted provided that the following conditions are met:

Redistributions of source code must retain the above copyright notice, this list of
conditions and the following disclaimer.

Redistributions in binary form must reproduce the above copyright notice, this list
of conditions and the following disclaimer in the documentation and/or other materials
provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE FREEBSD PROJECT ``AS IS'' AND ANY EXPRESS OR IMPLIED
WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE FREEBSD PROJECT OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

The views and conclusions contained in the software and documentation are those of the
authors and should not be interpreted as representing official policies, either expressed
or implied, of the FreeBSD Project.
"""

__doc__="""Based on Django Database backed models, provides a means for mapping models 
to xml, and specifying finders that map to a remote REST service.  For parsing XML
XPath expressions, xml_models attempts to use lxml if it is available.  If not, it 
uses pyxml_xpath.  Better performance will be gained by installing lxml."""

import unittest, re, datetime, time
import xpath_twister as xpath
from xml.etree import ElementTree as et
import rest_client


class NoRegisteredFinderError(Exception):
    pass
    
class DoesNotExist(Exception):
    
    def __init__(self, model, args):
        Exception.__init__(self, "DoesNotExist: %s matching query %s does not exist" %(model.__name__, str(args)))

class XmlValidationError(Exception):
    pass

class BaseField:
    """All fields must specify an xpath as a keyword arg in their constructor.  Fields may optionally specify a 
    default value using the default keyword arg."""
    def __init__(self, **kw):
        if not kw.has_key('xpath'):
            raise Exception('No XPath supplied for xml field')
        self.xpath = kw['xpath']
        self._default = kw.pop('default', None)
            
    
    def _fetch_by_xpath(self, xml_doc, namespace):
        find = xpath.find_unique(xml_doc, self.xpath, namespace)
        if find == None:
            return self._default
        return find

    
    def _parse(self, xml, namespace):
        try:
            return self.__cached_value
        except:
            self.__cached_value = self.parse(xml, namespace)
            return self.__cached_value
    
class CharField(BaseField):
    """Returns the single value found by the xpath expression, as a string"""
    def parse(self, xml, namespace):
        return self._fetch_by_xpath(xml, namespace)
        

class IntField(BaseField):
    """Returns the single value found by the xpath expression, as an int"""
    def parse(self, xml, namespace):
        value = self._fetch_by_xpath(xml, namespace)
        if value:
            return int(value)
        return self._default
    
class DateField(BaseField):
    """
    Returns the single value found by the xpath expression, as a datetime. By default, expects
    dates that match the ISO date format (same as Java JAXB supplies).  If a date_format keyword
    arg is supplied, that will be used instead.  Uses datetime.strptime under the hood, so the
    date_format should be defined according to strptime rules.
    
    We sometimes get dates that include a UTC offset.  We don't have a nice way to handle these, 
    so for now we are going to strip the offset and throw it away"""
    match_utcoffset = re.compile(r"(^.*?)[+|-]\d{2}:\d{2}$")
    
    def __init__(self, date_format="%Y-%m-%dT%H:%M:%S", **kw):
        BaseField.__init__(self,**kw)
        self.date_format = date_format
        
    def parse(self, xml, namespace):
        value = self._fetch_by_xpath(xml, namespace)
        if value:
            utc_stripped = self.match_utcoffset.findall(value)
            if len(utc_stripped) == 1:
                value = utc_stripped[0]
            try:
                return datetime.datetime.strptime(value, self.date_format)
            except ValueError, msg:
                if "%S" in self.date_format:
                    msg = str(msg)
                    rematch = re.match(r"unconverted data remains:"
                        " \.([0-9]{1,6})$", msg)
                    if rematch is not None:
                        frac = "." + rematch.group(1)
                        value = value[:-len(frac)]
                        value = datetime.datetime(*time.strptime(value, self.date_format)[0:6])
                        microsecond = int(float(frac)*1e6)
                        return value.replace(microsecond=microsecond)
                    else:
                        rematch = re.match(r"unconverted data remains:"
                            " \,([0-9]{3,3})$", msg)
                        if rematch is not None:
                            frac = "." + rematch.group(1)
                            value = value[:-len(frac)]
                            value = datetime.datetime(*time.strptime(value, self.date_format)[0:6])
                            microsecond = int(float(frac)*1e6)
                            return value.replace(microsecond=microsecond)
                raise
        return self._default
        
class FloatField(BaseField):
    """Returns the single value found by the xpath expression, as a float"""
    def parse(self, xml, namespace):
        value = self._fetch_by_xpath(xml, namespace)
        if value:
            return float(value)
        return self._default

class BoolField(BaseField):
    """Returns the single value found by the xpath expression, as a boolean"""
    def parse(self, xml, namespace):
        value = self._fetch_by_xpath(xml, namespace)
        if value is not None:
            if value.lower() == 'true':
                return True
            elif value.lower() == 'false':
                return False
        return self._default

class Collection(BaseField):
    """Returns a collection found by the xpath expression.  Requires a field_type to be supplied, which can
    either be a field type, e.g. IntField, which returns a collection ints, or it can be a model type
    e.g. Person may contain a collection of Address objects."""
    def __init__(self, field_type, order_by=None, **kw):
        self.field_type = field_type
        self.order_by = order_by
        BaseField.__init__(self,**kw)
        
    def parse(self, xml, namespace):
        matches = xpath.find_all(xml, self.xpath, namespace)

        if not BaseField in self.field_type.__bases__:
            
            results = [self.field_type(xml=match) for match in matches]
        else:
            field = self.field_type(xpath = '.')
            results = [field.parse(xpath.domify(match), namespace) for match in matches]
        if self.order_by:
            results.sort(lambda a,b : cmp(getattr(a, self.order_by), getattr(b, self.order_by)))
        return results
    
CollectionField = Collection

class OneToOneField(BaseField):
    def __init__(self, field_type, **kw):
        self.field_type = field_type
        BaseField.__init__(self,**kw)
        
    def parse(self, xml, namespace):
        match = xpath.find_all(xml, self.xpath, namespace)
        if len(match) == 1:
            return self.field_type(xml=match[0])
        return None
        
class ModelBase(type):
    "Meta class for declarative xml_model building"
    def __init__(cls, name, bases, attrs):
        xml_fields = [field_name for field_name in attrs.keys() if isinstance(attrs[field_name], BaseField)]
        for field_name in xml_fields:
            setattr(cls, field_name, cls._get_xpath(field_name, attrs[field_name]))
            attrs[field_name]._name = field_name
        if attrs.has_key("finders"):
            setattr(cls, "objects", XmlModelManager(cls, attrs["finders"]))
    
    def _get_xpath(cls, field_name, field_impl):
        return property(fget=lambda cls: cls._parse_field(field_impl), fset=lambda cls, value : cls._set_value(field_impl, value))
        
class XmlModelManager(object):
    """Handles what can be queried for, and acts as the entry point for querying.  There is an instance per model that is used
    in the django style of Model.objects.get(attr1=value, attr2=value2) for single results, or 
    Model.objects.filter(attr1=value1,attr2=value2) for multiple results.  As with Django, you can chain filters together, i.e.
    Model.objects.filter(attr1=value1).filter(attr2=value2)  Filter is not evaluated until you try to iterate over the results or
    get a count of the results."""
    def __init__(self, model, finders):
        self.model = model
        self.finders = {}
        for key in finders.keys():
            field_names = [field._name for field in key]
            sorted_field_names = list(field_names)
            sorted_field_names.sort()
            self.finders[tuple(sorted_field_names)] = (finders[key], field_names)

    def filter(self, **kw):        
        return XmlModelQuery(self, self.model).filter(**kw)

    def count(self):
        raise NoRegisteredFinderError("foo")
        
    def get(self, **kw):
        return XmlModelQuery(self, self.model).get(**kw)

class XmlModelQuery(object):

    def __init__(self, manager, model):
        self.manager = manager
        self.model = model
        self.args = {}

    def filter(self, **kw):
        for key in kw.keys():
            self.args[key] = kw[key]
        return self

    def count(self):
        response = rest_client.Client("").GET(self._find_query_path()) 
        count = 0
        for x in self._fragments(response.content):
            count += 1
        return count
        
    def __iter__(self):
        response = rest_client.Client("").GET(self._find_query_path()) 
        for x in self._fragments(response.content):
            yield self.model(xml=x)
            
    def __len__(self):
        return self.count()
        
    def get(self, **kw):
        for key in kw.keys():
            self.args[key] = kw[key]
        response = rest_client.Client("").GET(self._find_query_path())
        if not response.content:
            raise DoesNotExist(self.model, self.args)
        if response.response_code == 404:
            raise DoesNotExist(self.model, self.args)
        content = response.content.read()
        if not content:
            raise DoesNotExist(self.model, self.args)
        return self.model(xml=content)
        
    def _fragments(self, xml):
        tree = et.iterparse(xml, ['start','end'])
        tree.next()
        evt, child = tree.next()
        node_name = child.tag
        for event, elem in tree:
            if event == 'end' and elem.tag == node_name:
                result = et.tostring(elem)
                elem.clear()
                yield result

    def _find_query_path(self):
        keys = self.args.keys()
        keys.sort()
        key_tuple = tuple(keys)
        try:
            (url, attrs) = self.manager.finders[key_tuple]
            return url % tuple([ self.args[x] for x in attrs]) 
        except KeyError:
            raise NoRegisteredFinderError(str(key_tuple))

class Model:
    __metaclass__ = ModelBase
    __doc__="""A model can be constructed with either an xml string, or an appropriate document supplied by
    the xpath_twister.domify() method.
    
    An example:
    
    class Person(xml_models.Model):
        namespace="urn:my.default.namespace"
        name = xml_models.CharField(xpath"/Person/@Name", default="John")
        nicknames = xml_models.CollectionField(CharField, xpath="/Person/Nicknames/Name")
        addresses = xml_models.CollectionField(Address, xpath="/Person/Addresses/Address")
        date_of_birth = xml_models.DateField(xpath="/Person/@DateOfBirth", date_format="%d-%m-%Y")
    """
    def __init__(self, xml=None, dom=None):
        self._xml = xml
        self._dom = dom
        self._cache = {}
        self.validate_on_load()

    """Override on your model to perform validation when the XML data is first passed in. This is to ensure the xml returned
       conforms to the validation rules.  We use this because some records are no use to us if they don't contain certain
       data."""
    def validate_on_load(self):
        pass

    def _get_xml(self):
        if self._dom is None:
            try :
                self._dom = xpath.domify(self._xml)
            except Exception, e:
                print self._xml
                print str(e)
                raise e
        return self._dom
        
    def _set_value(self, field, value):
        self._cache[field] = value
        
    def _parse_field(self, field):
        if not self._cache.has_key(field):
            namespace = None
            if hasattr(self, 'namespace'):
                namespace = self.namespace
            self._cache[field] = field.parse(self._get_xml(), namespace)
        return self._cache[field]



